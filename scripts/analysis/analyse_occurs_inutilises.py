# scripts/analysis/analyse_occurs_inutilises.py
from __future__ import annotations

import csv
from pathlib import Path
from collections import defaultdict

# ============================================================
# Option (OFF by default)
# ------------------------------------------------------------
# If True, a WRITE on a parent group counts as "potential usage"
# for its children (including OCCURS tables).
#
# Why OFF by default:
# - Avoid hiding truly dead tables
# - Turn ON only when your codebase uses many MOVE group-to-group
#   patterns that make "strict" unused detection too noisy.
# ============================================================
COUNT_PARENT_WRITE_AS_CHILD_USAGE = False


def _read_csv_dict(path: Path, delimiter: str = ",") -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=delimiter))


def _write_csv_dict(path: Path, rows: list[dict], delimiter: str = ";") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({k for r in rows for k in r.keys()})
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, delimiter=delimiter, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _var_key_from_dd(row: dict) -> str:
    fp = (row.get("full_path") or "").strip()
    nm = (row.get("name") or "").strip()
    return fp or nm


def _usage_counts(usage_rows: list[dict]) -> dict[str, dict]:
    counts = defaultdict(lambda: {"nb_reads": 0, "nb_writes": 0, "nb_conditions": 0})
    for u in usage_rows:
        var = (u.get("variable") or "").strip()
        if not var:
            continue
        t = (u.get("usage_type") or "").strip().lower()
        if t == "read":
            counts[var]["nb_reads"] += 1
        elif t == "write":
            counts[var]["nb_writes"] += 1
        elif t == "condition":
            counts[var]["nb_conditions"] += 1
    return counts


def _total(c: dict) -> int:
    return int(c.get("nb_reads", 0)) + int(c.get("nb_writes", 0)) + int(c.get("nb_conditions", 0))


def _parent_full_path(full_path: str) -> str:
    fp = (full_path or "").strip()
    if not fp or "/" not in fp:
        return ""
    return fp.rsplit("/", 1)[0]


def analyse_occurs_inutilises(dd_csv_path: Path, usage_csv_path: Path, out_csv_path: Path) -> Path:
    """Detect OCCURS tables unused (strict) + optional "potential usage" via parent writes.

    Output rows are created only when an issue is found.

    Columns added in v2:
      - parent_full_path
      - parent_total_writes
      - note (for potential usage)
    """
    dd_rows = _read_csv_dict(dd_csv_path, delimiter=",")
    usage_rows = _read_csv_dict(usage_csv_path, delimiter=";")
    prog = (dd_rows[0].get("program") if dd_rows else "") or dd_csv_path.stem.replace("_dd", "")

    counts = _usage_counts(usage_rows)
    used_vars = list(counts.keys())

    out_rows: list[dict] = []

    for d in dd_rows:
        occurs = (d.get("occurs") or "").strip()
        if not occurs:
            continue

        table_key = _var_key_from_dd(d)
        table_fp = (d.get("full_path") or "").strip()
        depends_on = (d.get("occurs_depends_on") or "").strip()

        # Table usage = direct usage + usage of any child (prefix match)
        table_total = 0
        table_reads = 0
        table_writes = 0
        table_conds = 0

        if table_key in counts:
            c = counts[table_key]
            table_reads += int(c.get("nb_reads", 0))
            table_writes += int(c.get("nb_writes", 0))
            table_conds += int(c.get("nb_conditions", 0))

        if table_fp:
            prefix = table_fp + "/"
            for v in used_vars:
                if v.startswith(prefix):
                    c = counts[v]
                    table_reads += int(c.get("nb_reads", 0))
                    table_writes += int(c.get("nb_writes", 0))
                    table_conds += int(c.get("nb_conditions", 0))

        table_total = table_reads + table_writes + table_conds

        # Optional: consider parent writes as potential usage
        parent_fp = _parent_full_path(table_fp)
        parent_writes = 0
        if COUNT_PARENT_WRITE_AS_CHILD_USAGE and parent_fp:
            pc = counts.get(parent_fp, {"nb_reads": 0, "nb_writes": 0, "nb_conditions": 0})
            parent_writes = int(pc.get("nb_writes", 0))

        issues: list[str] = []
        severity = "INFO"
        note = ""

        if table_total == 0:
            # Strict unused
            issues.append("occurs_unused")
            severity = "MEDIUM"

            # If option ON and parent is written, downgrade to "potential usage"
            if COUNT_PARENT_WRITE_AS_CHILD_USAGE and parent_writes > 0:
                issues.append("potential_usage_via_parent_write")
                severity = "INFO"
                note = "Table non référencée directement, mais le parent est écrit (MOVE groupe possible)."

        # DEPENDING ON checks (unchanged)
        dep_writes = 0
        dep_total = 0
        if depends_on:
            dep_c = counts.get(depends_on, {"nb_reads": 0, "nb_writes": 0, "nb_conditions": 0})
            dep_writes = int(dep_c.get("nb_writes", 0))
            dep_total = _total(dep_c)
            if dep_total == 0:
                issues.append("depending_on_never_used")
                severity = "MEDIUM"
            elif dep_writes == 0:
                issues.append("depending_on_never_written")
                severity = "MEDIUM"

        if not issues:
            continue

        out_rows.append({
            "program": prog,
            "name": (d.get("name") or ""),
            "full_path": table_fp,
            "parent_full_path": parent_fp,
            "level": (d.get("level") or ""),
            "pic": (d.get("pic") or ""),
            "occurs": occurs,
            "occurs_depends_on": depends_on,
            "table_total_usage": table_total,
            "table_reads": table_reads,
            "table_writes": table_writes,
            "table_conditions": table_conds,
            "parent_total_writes": parent_writes,
            "depends_on_total_usage": dep_total,
            "depends_on_writes": dep_writes,
            "issue": ",".join(issues),
            "severity": severity,
            "note": note,
            "section": (d.get("section") or ""),
            "source": (d.get("source") or ""),
            "line_etude": (d.get("line_etude") or ""),
        })

    _write_csv_dict(out_csv_path, out_rows, delimiter=";")
    return out_csv_path
