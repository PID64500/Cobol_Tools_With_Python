"""
analyse_variables_critiques.py
--------------------------------
Objectif :
  Produire, par programme, un CSV "variables critiques" en croisant :
    - le dictionnaire de données (dd_by_program/<PGM>_dd.csv)
    - les usages (csv/<PGM>_usage.csv) issus de scan_variable_usage.py

Sortie :
  work_dir/csv/variables_critiques/<PGM>_variables_critiques.csv

Convention CSV :
  - séparateur : ';' (Excel-friendly)
  - encodage   : UTF-8 avec BOM (utf-8-sig) pour éviter les 'indÃ©terminÃ©'
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


# -----------------------------
# IO helpers
# -----------------------------

def _read_csv(path: Path, delimiter: str) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        return [{k: (v if v is not None else "") for k, v in row.items()} for row in reader]


def load_dd(dd_csv_path: Path) -> List[Dict[str, str]]:
    """
    Dictionnaire de données par programme.
    Attendu : CSV séparé par virgule (',') avec colonnes :
      program, section, source, level, name, parent_name, full_path, pic, ...
    """
    return _read_csv(dd_csv_path, delimiter=",")


def load_usage(usage_csv_path: Path) -> List[Dict[str, str]]:
    """
    Usages variables par programme.
    Attendu : CSV séparé par ';' avec colonnes :
      program;variable;usage_type;paragraph;line_etude;context_usage_final
    """
    return _read_csv(usage_csv_path, delimiter=";")


# -----------------------------
# Core
# -----------------------------

@dataclass(frozen=True)
class UsageAgg:
    usage_count: int
    nb_paragraphs: int
    nb_reads: int
    nb_writes: int
    nb_conditions: int
    nb_io: int


def _is_io_context(ctx: str) -> bool:
    u = (ctx or "").upper()
    # heuristique volontairement simple
    return ("READ " in u) or ("WRITE " in u) or ("REWRITE " in u) or ("DELETE " in u) or ("EXEC CICS" in u)


def _aggregate_usage(usage_rows: List[Dict[str, str]]) -> Dict[str, UsageAgg]:
    """
    Agrège par variable (full_path) les stats issues de scan_variable_usage.
    """
    by_var: Dict[str, Dict[str, object]] = {}

    for r in usage_rows:
        var = (r.get("variable") or "").strip()
        if not var:
            continue

        usage_type = (r.get("usage_type") or "").strip().lower()
        paragraph = (r.get("paragraph") or "").strip()
        ctx = (r.get("context_usage_final") or "")

        d = by_var.setdefault(var, {
            "reads": 0,
            "writes": 0,
            "conditions": 0,
            "io": 0,
            "paras": set(),
        })

        if paragraph:
            d["paras"].add(paragraph)

        if usage_type == "read":
            d["reads"] += 1
        elif usage_type == "write":
            d["writes"] += 1
        elif usage_type == "condition":
            d["conditions"] += 1
        else:
            # type non standard -> neutre
            d["reads"] += 1

        if _is_io_context(ctx):
            d["io"] += 1

    out: Dict[str, UsageAgg] = {}
    for var, d in by_var.items():
        reads = int(d["reads"])
        writes = int(d["writes"])
        cond = int(d["conditions"])
        io = int(d["io"])
        paras = d["paras"]
        usage_count = reads + writes + cond
        out[var] = UsageAgg(
            usage_count=usage_count,
            nb_paragraphs=len(paras),
            nb_reads=reads,
            nb_writes=writes,
            nb_conditions=cond,
            nb_io=io,
        )
    return out


def _root_name_from_full_path(full_path: str) -> str:
    fp = (full_path or "").strip()
    if not fp:
        return ""
    return fp.split("/")[0]


def _infer_role(name: str, pic: str) -> str:
    """
    Heuristique volontairement simple.
    """
    n = (name or "").upper()
    p = (pic or "").upper()

    if "DATE" in n or "DAT" in n:
        return "date"
    if "TIME" in n or "HEUR" in n:
        return "heure"
    if "STAT" in n or "STATUS" in n:
        return "statut"
    if "CODE" in n or "COD" in n:
        return "code"
    if "NOM" in n or "NAME" in n:
        return "nom"
    if "ID" in n:
        return "identifiant"
    if p.startswith(("9", "S9")):
        return "numerique"
    return "indéterminé"


def _is_critical(agg: UsageAgg, name: str, level: str) -> bool:
    """
    Criticité pragmatique :
    - ignore niveau 88
    - critique si écrit (modification) OU très utilisé
    """
    if (level or "").strip() == "88":
        return False

    if agg.nb_writes > 0:
        return True

    if agg.usage_count >= 30:
        return True

    n = (name or "").upper()
    if any(k in n for k in ["RESP", "RETOUR", "ERR", "ANOM", "ABEND"]):
        return agg.usage_count > 0

    return False


def build_variables_critiques(
    dd_rows: List[Dict[str, str]],
    usage_rows: List[Dict[str, str]],
) -> List[Dict[str, object]]:
    """
    Produit les lignes finales (une ligne par variable DD).
    """
    usage_agg = _aggregate_usage(usage_rows)

    results: List[Dict[str, object]] = []

    for e in dd_rows:
        level = (e.get("level") or "").strip()
        if level == "88":
            continue

        full_path = (e.get("full_path") or "").strip()
        name = (e.get("name") or "").strip()

        agg = usage_agg.get(full_path) or usage_agg.get(name)
        if not agg:
            agg = UsageAgg(0, 0, 0, 0, 0, 0)

        usage_flag = "Y" if agg.usage_count > 0 else "N"

        row = {
            "program": (e.get("program") or "").strip(),
            "section": (e.get("section") or "").strip(),
            "source": (e.get("source") or "").strip(),
            "root_name": _root_name_from_full_path(full_path or name),
            "name": name,
            "full_path": full_path or name,
            "level": level,
            "pic": (e.get("pic") or "").strip(),
            "usage_flag": usage_flag,
            "usage_count": agg.usage_count,
            "nb_paragraphs": agg.nb_paragraphs,
            "nb_reads": agg.nb_reads,
            "nb_writes": agg.nb_writes,
            "nb_conditions": agg.nb_conditions,
            "nb_io": agg.nb_io,
            "has_88": "N",
            "nb_88": 0,
            "is_critical": "Y" if _is_critical(agg, name, level) else "N",
            "role_infered": _infer_role(name, (e.get("pic") or "")),
        }
        results.append(row)

    results.sort(key=lambda r: (-(int(r.get("usage_count") or 0)), str(r.get("full_path") or "")))
    return results


def write_variables_critiques_csv(out_csv_path: Path, rows: List[Dict[str, object]]) -> None:
    out_csv_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "program",
        "section",
        "source",
        "root_name",
        "name",
        "full_path",
        "level",
        "pic",
        "usage_flag",
        "usage_count",
        "nb_paragraphs",
        "nb_reads",
        "nb_writes",
        "nb_conditions",
        "nb_io",
        "has_88",
        "nb_88",
        "is_critical",
        "role_infered",
    ]

    with out_csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def analyse_variables_critiques(
    dict_csv_path: Path,
    usage_csv_path: Path,
    out_csv_path: Path,
) -> int:
    """
    API pipeline : retourne 0 si OK, 1 si KO.
    """
    if not dict_csv_path.exists():
        raise FileNotFoundError(f"DD manquant : {dict_csv_path}")
    if not usage_csv_path.exists():
        raise FileNotFoundError(f"USAGE manquant : {usage_csv_path}")

    dd_rows = load_dd(dict_csv_path)
    usage_rows = load_usage(usage_csv_path)

    rows = build_variables_critiques(dd_rows, usage_rows)
    write_variables_critiques_csv(out_csv_path, rows)
    return 0
