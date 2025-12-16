# scripts/analysis/analyse_redefines_dangereux.py
from __future__ import annotations

import csv
import re
from pathlib import Path
from collections import defaultdict

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

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

def _is_filler_name(name: str | None) -> bool:
    return (name or "").strip().upper() == "FILLER"

def _pic_signature(pic: str | None) -> dict:
    """Pragmatic PIC signature for compatibility checks.
    We deliberately treat missing/empty PIC as 'EMPTY' to avoid false HIGH.
    """
    p = (pic or "").strip().upper()
    if not p:
        return {"class": "EMPTY", "size": None, "storage": "EMPTY", "raw": ""}

    storage = "DISPLAY"
    if "COMP-3" in p or "PACKED-DECIMAL" in p:
        storage = "COMP-3"
    elif "COMP" in p or "BINARY" in p:
        storage = "COMP"

    if "X" in p:
        cls = "ALPHA"
    elif "9" in p:
        cls = "NUM"
    else:
        cls = "OTHER"

    size = 0
    found = False
    for m in re.finditer(r"(X|9)\((\d+)\)", p):
        found = True
        size += int(m.group(2))
    if not found:
        size = None

    return {"class": cls, "size": size, "storage": storage, "raw": p}

def _usage_counts_from_usage_rows(usage_rows: list[dict]) -> dict[str, dict]:
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

# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def analyse_redefines_dangereux(dd_csv_path: Path, usage_csv_path: Path, out_csv_path: Path) -> Path:
    """Détection des REDEFINES potentiellement dangereux.

    Durcissements (anti faux HIGH) :
      - FILLER exclus des comparaisons PIC
      - PIC vides exclus des comparaisons PIC
      - 'pic_incompatible_within_group' seulement si >= 2 PIC non vides (et non-FILLER)
    """
    dd_rows = _read_csv_dict(dd_csv_path, delimiter=",")
    usage_rows = _read_csv_dict(usage_csv_path, delimiter=";")

    prog = (dd_rows[0].get("program") if dd_rows else "") or dd_csv_path.stem.replace("_dd", "")
    usage_counts = _usage_counts_from_usage_rows(usage_rows)

    # Index by name for matching redefines target
    by_name = defaultdict(list)
    for r in dd_rows:
        nm = (r.get("name") or "").strip()
        if nm:
            by_name[nm].append(r)

    # Groups: key = (redefines_target, parent_name)
    groups = defaultdict(list)
    for r in dd_rows:
        redef = (r.get("redefines") or "").strip()
        if redef:
            groups[(redef, (r.get("parent_name") or "").strip())].append(r)

    out_rows: list[dict] = []

    for (redef_target, parent_name), redef_items in groups.items():
        # Also include the target itself if present
        target_candidates = by_name.get(redef_target, [])
        target = None
        if len(target_candidates) == 1:
            target = target_candidates[0]
        else:
            for cand in target_candidates:
                if (cand.get("parent_name") or "").strip() == parent_name:
                    target = cand
                    break
            if target_candidates and target is None:
                target = target_candidates[0]

        members = []
        if target:
            members.append(target)
        members.extend(redef_items)

        member_infos = []
        for m in members:
            key = _var_key_from_dd(m)
            c = usage_counts.get(key, {"nb_reads": 0, "nb_writes": 0, "nb_conditions": 0})
            pic_sig = _pic_signature(m.get("pic"))
            member_infos.append((m, c, pic_sig))

        # Active alternatives (exclude FILLER from the "alternatives" list)
        active = [
            mi for mi in member_infos
            if _total(mi[1]) > 0 and not _is_filler_name(mi[0].get("name"))
        ]
        active_names = [mi[0].get("name", "") for mi in active if mi[0].get("name")]

        # PIC incompatibilities within group (strict, avoid false highs)
        comparable_sigs = [
            mi[2]
            for mi in member_infos
            if mi[2].get("raw")  # non-empty PIC
            and not _is_filler_name(mi[0].get("name"))
        ]

        incompatible = False
        incompat_reasons: list[str] = []

        if len(comparable_sigs) >= 2:
            cls_set = {s.get("class") for s in comparable_sigs}
            stor_set = {s.get("storage") for s in comparable_sigs}
            sizes = {s.get("size") for s in comparable_sigs if s.get("size") is not None}

            if len(cls_set) > 1:
                incompatible = True
                incompat_reasons.append(f"class={sorted(cls_set)}")
            if len(stor_set) > 1:
                incompatible = True
                incompat_reasons.append(f"storage={sorted(stor_set)}")
            if len(sizes) > 1:
                incompatible = True
                incompat_reasons.append(f"size={sorted(sizes)}")

        for m, c, _ in member_infos:
            issue: list[str] = []
            severity = "INFO"

            if _total(c) == 0:
                issue.append("redefines_unused")
                severity = "MEDIUM"

            # Multiple active non-filler alternatives => risky
            if len(active) >= 2:
                issue.append("multiple_redefines_active")
                severity = "HIGH"

            # Only raise PIC incompatibility when we have >=2 comparable PICs
            if incompatible:
                issue.append("pic_incompatible_within_group")
                severity = "HIGH"

            if not issue:
                continue

            out_rows.append({
                "program": prog,
                "redefines_target": redef_target,
                "parent_name": parent_name,
                "name": (m.get("name") or ""),
                "full_path": (m.get("full_path") or ""),
                "level": (m.get("level") or ""),
                "pic": (m.get("pic") or ""),
                "nb_reads": c.get("nb_reads", 0),
                "nb_writes": c.get("nb_writes", 0),
                "nb_conditions": c.get("nb_conditions", 0),
                "total_usage": _total(c),
                "active_alternatives": ",".join(active_names),
                "issue": ",".join(issue),
                "severity": severity,
                "pic_group_notes": ";".join(incompat_reasons),
                "section": (m.get("section") or ""),
                "source": (m.get("source") or ""),
                "line_etude": (m.get("line_etude") or ""),
            })

    _write_csv_dict(out_csv_path, out_rows, delimiter=";")
    return out_csv_path
