# scripts/analysis/analyse_niveaux_cobol.py
from __future__ import annotations

import csv
from pathlib import Path

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

def _parse_level(v: str | None) -> int | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None

def _parse_line(v: str | None) -> int:
    if v is None:
        return 0
    s = str(v).strip()
    if not s:
        return 0
    try:
        return int(s)
    except ValueError:
        return 0

def analyse_niveaux_cobol(dd_csv_path: Path, out_csv_path: Path) -> Path:
    dd_rows = _read_csv_dict(dd_csv_path, delimiter=",")
    prog = (dd_rows[0].get("program") if dd_rows else "") or dd_csv_path.stem.replace("_dd", "")

    by_full = {}
    for r in dd_rows:
        fp = (r.get("full_path") or "").strip()
        if fp:
            by_full[fp] = r

    dd_rows_sorted = sorted(dd_rows, key=lambda r: _parse_line(r.get("line_etude")))

    out_rows: list[dict] = []

    for r in dd_rows_sorted:
        name = (r.get("name") or "").strip()
        fp = (r.get("full_path") or "").strip()
        parent_name = (r.get("parent_name") or "").strip()
        lvl = _parse_level(r.get("level"))

        if lvl is None:
            continue
        if lvl == 88:
            continue

        parent_fp = ""
        parent_row = None
        if fp and "/" in fp:
            parent_fp = fp.rsplit("/", 1)[0]
            parent_row = by_full.get(parent_fp)

        parent_lvl = _parse_level(parent_row.get("level")) if parent_row else None

        issues: list[str] = []

        if parent_row and lvl == 1:
            issues.append("level_01_has_parent")

        if lvl == 77 and parent_row:
            issues.append("level_77_has_parent")

        if parent_lvl is not None:
            if parent_lvl in range(1, 50) and lvl in range(2, 50) and lvl <= parent_lvl:
                issues.append("child_level_not_greater_than_parent")
            if parent_lvl == 77:
                issues.append("parent_level_77_has_children")

        if parent_lvl == 1:
            if lvl == 1:
                issues.append("invalid_child_level_under_01")
            if lvl not in range(2, 50) and lvl not in (66, 77, 88):
                issues.append("unexpected_child_level_under_01")

        if not issues:
            continue

        out_rows.append({
            "program": prog,
            "line_etude": (r.get("line_etude") or ""),
            "name": name,
            "full_path": fp,
            "level": (r.get("level") or ""),
            "parent_name": parent_name,
            "parent_full_path": parent_fp,
            "parent_level": parent_row.get("level") if parent_row else "",
            "issue": ",".join(issues),
            "section": (r.get("section") or ""),
            "source": (r.get("source") or ""),
        })

    _write_csv_dict(out_csv_path, out_rows, delimiter=";")
    return out_csv_path
