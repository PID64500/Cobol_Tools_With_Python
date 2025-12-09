#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyse_structures_logiques.py
------------------------------

À partir de :
  - d'un CSV dictionnaire (build_data_dictionary.py)
  - d'un CSV d'usage des variables (scan_variable_usage.py)

Produit :
  - un CSV "structures_logiques" avec une ligne par structure racine (01/05),
    résumant la taille et l'utilisation du bloc de données.

Usage :
  python analyse_structures_logiques.py prog_dd.csv prog_usage.csv --out prog_structures.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, List


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyse les structures logiques (blocs racines) d'un programme COBOL."
    )
    parser.add_argument("dict_csv", help="CSV dictionnaire (sortie de build_data_dictionary.py)")
    parser.add_argument("usage_csv", help="CSV usage (sortie de scan_variable_usage.py)")
    parser.add_argument(
        "--out",
        default="structures_logiques.csv",
        help="CSV de sortie (défaut : structures_logiques.csv)",
    )
    return parser.parse_args()


def load_csv(path: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def index_usage(usage_rows: List[Dict[str, str]]) -> Dict[tuple, Dict[str, str]]:
    """
    Indexe les infos d'usage par (program, section, name, full_path).

    On suppose que scan_variable_usage.py a ajouté au moins :
      - used
      - usage_count
      - first_usage_line
    """
    index: Dict[tuple, Dict[str, str]] = {}
    for r in usage_rows:
        key = (
            (r.get("program") or "").upper(),
            (r.get("section") or "").upper(),
            (r.get("name") or "").upper(),
            (r.get("full_path") or "").upper(),
        )
        index[key] = r
    return index


def enrich_dict_with_usage(
    dict_rows: List[Dict[str, str]],
    usage_index: Dict[tuple, Dict[str, str]],
) -> None:
    """
    Ajoute les colonnes d'usage (used, usage_count, first_usage_line)
    dans les lignes du dictionnaire, à partir de l'index usage.
    """
    for e in dict_rows:
        key = (
            (e.get("program") or "").upper(),
            (e.get("section") or "").upper(),
            (e.get("name") or "").upper(),
            (e.get("full_path") or "").upper(),
        )
        u = usage_index.get(key)
        if u:
            e["used"] = u.get("used", "N")
            e["usage_count"] = u.get("usage_count", "0")
            e["first_usage_line"] = u.get("first_usage_line", "")
        else:
            # Par défaut, si pas trouvé dans usage
            e.setdefault("used", "N")
            e.setdefault("usage_count", "0")
            e.setdefault("first_usage_line", "")


def is_root_structure(e: Dict[str, str]) -> bool:
    """
    Détermine si une entrée du dictionnaire est une 'structure racine'.

    Règle V1 :
      - level = 01 ou 05
      - parent_name vide
    """
    level = (e.get("level") or "").strip()
    parent = (e.get("parent_name") or "").strip()
    if parent:
        return False
    return level in ("01", "05")


def analyse_structures(dict_rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Construit la vue 'structures_logiques' à partir du dictionnaire enrichi.

    Sortie : une liste de dicts avec colonnes :
      program, section, source, root_name, level, full_path,
      nb_children, nb_children_used, has_occurs, has_88,
      used, usage_count_total, first_usage_line
    """
    results: List[Dict[str, str]] = []

    # On peut traiter plusieurs programmes dans un même CSV,
    # donc on ne suppose pas un programme unique.
    for root in dict_rows:
        if not is_root_structure(root):
            continue

        program = root.get("program", "")
        section = root.get("section", "")
        source = root.get("source", "")
        root_name = root.get("name", "")
        level = root.get("level", "")
        root_fp = root.get("full_path") or root_name

        # Collecter tous les descendants (y compris la racine)
        descendants: List[Dict[str, str]] = []
        for e in dict_rows:
            if (e.get("program", "") != program) or (e.get("section", "") != section):
                continue
            fp = e.get("full_path") or e.get("name", "")
            if fp == root_fp or fp.startswith(root_fp + "/"):
                descendants.append(e)

        # Séparer racine / enfants
        children = [e for e in descendants if (e is not root)]

        # Calculs
        nb_children = len(children)
        nb_children_used = sum(1 for e in children if (e.get("used") or "N") == "Y")

        has_occurs = any((e.get("occurs") or "").strip() not in ("", "0") for e in descendants)
        has_88 = any((e.get("level") or "").strip() == "88" for e in descendants)

        # Une structure est considérée 'used' si :
        # - la racine est utilisée, ou
        # - au moins un enfant est utilisé
        used_root = (root.get("used") or "N") == "Y"
        used_children = nb_children_used > 0
        used_flag = "Y" if (used_root or used_children) else "N"

        # usage_count_total = somme des usage_count des descendants
        total_usage = 0
        first_usage_line = ""
        for e in descendants:
            try:
                cnt = int(e.get("usage_count", "0") or "0")
            except ValueError:
                cnt = 0
            total_usage += cnt

            # On prend la plus petite ligne non vide comme "première utilisation"
            line = (e.get("first_usage_line") or "").strip()
            if line:
                if not first_usage_line:
                    first_usage_line = line
                else:
                    # Comparaison naïve en numérique si possible
                    try:
                        cur = int(first_usage_line)
                        new = int(line)
                        if new < cur:
                            first_usage_line = line
                    except ValueError:
                        # Au pire, on garde la première trouvée
                        pass

        result = {
            "program": program,
            "section": section,
            "source": source,
            "root_name": root_name,
            "level": level,
            "full_path": root_fp,
            "nb_children": str(nb_children),
            "nb_children_used": str(nb_children_used),
            "has_occurs": "Y" if has_occurs else "N",
            "has_88": "Y" if has_88 else "N",
            "used": used_flag,
            "usage_count_total": str(total_usage),
            "first_usage_line": first_usage_line,
        }
        results.append(result)

    return results


def write_structures_csv(structures: List[Dict[str, str]], out_path: Path) -> None:
    if not structures:
        print("[AVERTISSEMENT] Aucune structure racine trouvée.")
        return

    fieldnames = [
        "program",
        "section",
        "source",
        "root_name",
        "level",
        "full_path",
        "nb_children",
        "nb_children_used",
        "has_occurs",
        "has_88",
        "used",
        "usage_count_total",
        "first_usage_line",
    ]

    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in structures:
            writer.writerow(r)


def main() -> int:
    args = parse_args()
    dict_csv_path = Path(args.dict_csv)
    usage_csv_path = Path(args.usage_csv)
    out_csv_path = Path(args.out)

    if not dict_csv_path.exists():
        print(f"[ERREUR] Dictionnaire introuvable : {dict_csv_path}")
        return 1
    if not usage_csv_path.exists():
        print(f"[ERREUR] Fichier d'usage introuvable : {usage_csv_path}")
        return 1

    dict_rows = load_csv(dict_csv_path)
    usage_rows = load_csv(usage_csv_path)

    usage_index = index_usage(usage_rows)
    enrich_dict_with_usage(dict_rows, usage_index)

    structures = analyse_structures(dict_rows)
    write_structures_csv(structures, out_csv_path)

    print(f"[OK] Structures logiques générées dans : {out_csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
