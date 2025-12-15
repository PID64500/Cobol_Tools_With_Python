#!/usr/bin/env python3
"""
analyse_structures_logiques.py

Analyse logique des structures de données COBOL à partir :
- du dictionnaire de données par programme (dd_by_program/<PGM>_dd.csv)
- des usages variables détectés (csv/<PGM>_usage.csv)

Sortie :
- un CSV synthétique par programme : csv/structures_logiques/structures_logiques_<PGM>.csv

Correctif V3+ :
- déduction du parent via full_path (avant le dernier '/')
- parcours itératif + visited => pas de RecursionError, pas de boucles
- auto-détection séparateur ';' ou ','
- dédoublonnage des usages par line_etude
- 2 compteurs :
    * usages_root_only : usages du seul noeud racine (comparable à Notepad si tu cherches le nom du 01)
    * usages_structure : usages cumulés (racine + descendants)
"""

from pathlib import Path
import csv
import argparse
from collections import defaultdict


# ============================================================
#   Chargement CSV (auto-détection séparateur)
# ============================================================

def _detect_delimiter(sample: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,")
        return dialect.delimiter
    except Exception:
        return ";" if sample.count(";") >= sample.count(",") else ","


def load_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        delim = _detect_delimiter(sample)
        reader = csv.DictReader(f, delimiter=delim)
        return list(reader)


# ============================================================
#   Index usages (tolérant aux noms de colonnes)
# ============================================================

def index_usage(usage_rows: list[dict]) -> dict:
    index = defaultdict(list)
    for row in usage_rows:
        var = (row.get("variable") or row.get("full_path") or row.get("name") or "").strip()
        if var:
            index[var].append(row)
    return index


def _usage_lines(usages: list[dict]) -> set[str]:
    """
    Retourne l'ensemble des line_etude (ou line) uniques pour une liste d'usages.
    -> 1 ligne = 1 utilisation (définition alignée "Notepad = lignes")
    """
    s = set()
    for u in usages:
        v = (u.get("line_etude") or u.get("line") or "").strip()
        if v:
            s.add(v)
    return s


def enrich_dict_with_usage(dict_rows: list[dict], usage_index: dict) -> None:
    for row in dict_rows:
        full_path = (row.get("full_path") or "").strip()
        name = (row.get("name") or "").strip()

        # On prend full_path si possible, sinon name.
        # IMPORTANT : on dédoublonne ensuite par line_etude.
        usages = usage_index.get(full_path) or usage_index.get(name) or []

        ulines = _usage_lines(usages)
        row["_usage_lines"] = ulines  # set[str]
        row["_usage_count"] = len(ulines)
        row["_first_usage_line"] = min(ulines) if ulines else ""


# ============================================================
#   Arbre via full_path (anti-ambigüité FILLER)
# ============================================================

def _node_id(row: dict) -> str:
    # full_path doit être unique
    fp = (row.get("full_path") or "").strip()
    if fp:
        return fp
    # fallback (rare) : name seul
    return (row.get("name") or "").strip()


def _parent_id(node_id: str) -> str:
    # Parent = chemin avant le dernier "/"
    if "/" in node_id:
        return node_id.rsplit("/", 1)[0]
    return ""


def build_children_index(dict_rows: list[dict]) -> tuple[dict, dict]:
    """
    Retourne :
    - children_index[parent_id] -> [child_row, ...]
    - rows_by_id[node_id] -> row
    """
    children_index = defaultdict(list)
    rows_by_id = {}

    for row in dict_rows:
        nid = _node_id(row)
        if not nid:
            continue
        rows_by_id[nid] = row
        pid = _parent_id(nid)
        children_index[pid].append(row)

    return children_index, rows_by_id


# ============================================================
#   Analyse structures (itératif)
# ============================================================

def collect_subtree_iter(root_id: str, children_index: dict) -> list[dict]:
    """
    Récupère tous les descendants d'une structure root_id (full_path),
    en itératif, avec visited pour éviter boucles.
    """
    collected = []
    visited = set()
    stack = list(children_index.get(root_id, []))

    while stack:
        node = stack.pop()
        nid = _node_id(node)
        if not nid:
            continue
        if nid in visited:
            continue
        visited.add(nid)

        collected.append(node)
        stack.extend(children_index.get(nid, []))

    return collected


def analyse_structures(dict_rows: list[dict]) -> list[dict]:
    structures = []
    children_index, _ = build_children_index(dict_rows)

    for row in dict_rows:
        level = (row.get("level") or "").strip()
        nid = _node_id(row)
        if not nid:
            continue

        # Racine = pas de parent (pas de "/") OU parent_id vide
        pid = _parent_id(nid)

        # On garde 01 et 05 en racines (comme ton script actuel)
        if level not in {"01", "05"}:
            continue
        if pid != "":
            continue

        subtree = collect_subtree_iter(nid, children_index)
        all_nodes = [row] + subtree

        # usages_root_only : comparable à une recherche Notepad sur le nom du 01/05
        root_lines = set(row.get("_usage_lines") or set())

        # usages_structure : cumul racine + descendants (dédoublonné par line_etude)
        struct_lines = set()
        for n in all_nodes:
            struct_lines |= set(n.get("_usage_lines") or set())

        structures.append({
            "structure": nid,  # full_path
            "level": level,
            "nb_elements": len(all_nodes),
            "usages_root_only": len(root_lines),
            "usages_structure": len(struct_lines),
            "has_occurs": any((n.get("occurs") or "").strip() for n in all_nodes),
            "has_level_88": any((n.get("level") or "").strip() == "88" for n in all_nodes),
            "first_usage_line": min(
                (n.get("_first_usage_line") for n in all_nodes if (n.get("_first_usage_line") or "").strip()),
                default=""
            ),
        })

    return structures


# ============================================================
#   Écriture CSV
# ============================================================

def write_structures_csv(structures: list[dict], out_csv: Path) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    fields = [
        "structure",
        "level",
        "nb_elements",
        "usages_root_only",
        "usages_structure",
        "has_occurs",
        "has_level_88",
        "first_usage_line",
    ]

    with out_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, delimiter=";")
        writer.writeheader()
        writer.writerows(structures)


# ============================================================
#   API PIPELINE
# ============================================================

def analyse_structures_logiques(
    dict_csv_path: Path,
    usage_csv_path: Path,
    out_csv_path: Path,
) -> Path:
    dict_rows = load_csv(dict_csv_path)
    usage_rows = load_csv(usage_csv_path)

    usage_index = index_usage(usage_rows)
    enrich_dict_with_usage(dict_rows, usage_index)

    structures = analyse_structures(dict_rows)
    write_structures_csv(structures, out_csv_path)

    return out_csv_path


# ============================================================
#   CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Analyse des structures logiques COBOL")
    parser.add_argument("dict_csv", type=Path)
    parser.add_argument("usage_csv", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    analyse_structures_logiques(args.dict_csv, args.usage_csv, args.out)


if __name__ == "__main__":
    main()
