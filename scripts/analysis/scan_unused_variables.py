# scripts/analysis/scan_unused_variables.py
from __future__ import annotations

import csv
from pathlib import Path
from collections import defaultdict

# --- Réglages de consolidation N1.1 ---
# FILLER : catégorie dédiée (ne pollue pas unused/write_only/read_only)
KEEP_FILLER_AS_STRUCTURAL = True  # si False => FILLER exclus du rapport


def _read_csv_dict(path: Path, delimiter: str = ",") -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=delimiter))


def _write_csv_dict(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fieldnames = sorted({k for r in rows for k in r.keys()})
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore", delimiter=";")
        w.writeheader()
        w.writerows(rows)


def _var_key_from_dd(dd_row: dict) -> str:
    # Clé variable unique : full_path si présent, sinon name
    fp = (dd_row.get("full_path") or "").strip()
    nm = (dd_row.get("name") or "").strip()
    return fp or nm


def _is_filler(dd_row: dict) -> bool:
    return (dd_row.get("name") or "").strip().upper() == "FILLER"


def _classify(nb_reads: int, nb_writes: int, nb_conditions: int, dd_row: dict) -> str | None:
    # A) FILLER : catégorie dédiée (ou exclusion)
    if _is_filler(dd_row):
        return "structural_filler" if KEEP_FILLER_AS_STRUCTURAL else None

    # Variable "utilisée" = read OR write OR condition
    used = (nb_reads + nb_writes + nb_conditions) > 0

    if not used:
        return "unused"

    # B) read_only affiné
    if nb_reads > 0 and nb_writes == 0:
        return "read_only_control" if nb_conditions > 0 else "read_only_constant"

    if nb_writes > 0 and nb_reads == 0 and nb_conditions == 0:
        return "write_only"

    # Cas restant : utilisée “normalement” (read+write, etc.) => on ne remonte pas
    return None


def _counts_from_usage_rows(usage_rows: list[dict]) -> tuple[int, int, int]:
    nb_reads = nb_writes = nb_conditions = 0
    for r in usage_rows:
        t = (r.get("usage_type") or "").strip().lower()
        if t == "read":
            nb_reads += 1
        elif t == "write":
            nb_writes += 1
        elif t == "condition":
            nb_conditions += 1
    return nb_reads, nb_writes, nb_conditions


def scan_unused_variables(
    csv_dir: Path,
    dd_by_program_dir: Path,
    out_dir: Path | None = None,
) -> dict:
    """
    Consolidation Niveau 1.1 : variables inutilisées / write-only / read-only (affiné) + FILLER structurels.

    Entrées attendues :
      - {csv_dir}/*.csv usages (ex: SRSRA130_usage.csv) en ; avec colonnes:
          program;variable;usage_type;paragraph;line_etude;context_usage_final
      - {dd_by_program_dir}/{PROG}_dd.csv en , avec colonnes:
          program,section,source,level,name,parent_name,full_path,pic,...

    Sorties :
      - {out_dir}/unused_variables_global.csv (;)  (C: nom figé)
      - {out_dir}/by_program/{PROG}_unused_variables.csv (;)
    """
    csv_dir = Path(csv_dir)
    dd_by_program_dir = Path(dd_by_program_dir)
    if out_dir is None:
        out_dir = csv_dir / "unused_variables"
    else:
        out_dir = Path(out_dir)

    by_program_dir = out_dir / "by_program"
    by_program_dir.mkdir(parents=True, exist_ok=True)

    global_rows: list[dict] = []
    per_program_outputs: dict[str, Path] = {}

    # Liste des usage.csv
    usage_files = sorted(csv_dir.glob("*_usage.csv"))

    for usage_path in usage_files:
        prog = usage_path.name.replace("_usage.csv", "").strip().upper()
        dd_path = dd_by_program_dir / f"{prog}_dd.csv"
        if not dd_path.is_file():
            continue

        dd_rows = _read_csv_dict(dd_path, delimiter=",")
        usage_rows = _read_csv_dict(usage_path, delimiter=";")

        # Index usage par variable
        usage_by_var: dict[str, list[dict]] = defaultdict(list)
        for u in usage_rows:
            var = (u.get("variable") or "").strip()
            if var:
                usage_by_var[var].append(u)

        program_out_rows: list[dict] = []

        for d in dd_rows:
            var_key = _var_key_from_dd(d)
            if not var_key:
                continue

            rows_u = usage_by_var.get(var_key, [])
            nb_reads, nb_writes, nb_conditions = _counts_from_usage_rows(rows_u)

            cat = _classify(nb_reads, nb_writes, nb_conditions, d)
            if cat is None:
                continue

            out = {
                "categories": cat,
                "program": d.get("program") or prog,
                "section": d.get("section", ""),
                "source": d.get("source", ""),
                "level": d.get("level", ""),
                "name": d.get("name", ""),
                "variable": var_key,
                "pic": d.get("pic", ""),
                "occurs": d.get("occurs", ""),
                "occurs_depends_on": d.get("occurs_depends_on", ""),
                "redefines": d.get("redefines", ""),
                "usage_decl": d.get("usage", ""),
                "line_etude": d.get("line_etude", ""),
                "nb_reads": nb_reads,
                "nb_writes": nb_writes,
                "nb_conditions": nb_conditions,
            }

            program_out_rows.append(out)
            global_rows.append(out)

        # Écriture par programme
        prog_out_path = by_program_dir / f"{prog}_unused_variables.csv"
        _write_csv_dict(prog_out_path, program_out_rows)
        per_program_outputs[prog] = prog_out_path

    # Écriture globale (C: nom figé)
    global_out_path = out_dir / "unused_variables_global.csv"
    _write_csv_dict(global_out_path, global_rows)

    return {
        "global": global_out_path,
        "by_program": per_program_outputs,
    }
