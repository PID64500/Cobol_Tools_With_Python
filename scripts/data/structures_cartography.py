# scripts/data/structures_cartography.py
from __future__ import annotations

import csv
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple, Optional

DEFAULT_CONCEPT = "TECHNIQUE_CONTROLE"


def _sniff_delimiter(path: Path, candidates: Tuple[str, ...] = (";", ",", "\t", "|")) -> str:
    sample = path.read_text(encoding="utf-8", errors="ignore").splitlines()[:5]
    if not sample:
        return ";"
    header = sample[0]
    best = ";"
    best_count = -1
    for d in candidates:
        c = header.count(d)
        if c > best_count:
            best = d
            best_count = c
    return best


def _read_dict_rows(path: Path, delimiter: Optional[str] = None) -> List[Dict[str, str]]:
    if delimiter is None:
        delimiter = _sniff_delimiter(path)
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        if reader.fieldnames:
            reader.fieldnames = [fn.strip().lstrip("\ufeff") for fn in reader.fieldnames]
        rows: List[Dict[str, str]] = []
        for r in reader:
            rows.append({(k.strip().lstrip("\ufeff") if k else k): (v.strip() if isinstance(v, str) else v) for k, v in r.items()})
        return rows


def _load_rules(rules_csv: Path) -> List[Dict[str, str]]:
    rules = _read_dict_rows(rules_csv, delimiter=";")
    cleaned = []
    for r in rules:
        if not r:
            continue
        if not r.get("concept") or not r.get("pattern"):
            continue
        try:
            r["priority"] = int(r.get("priority") or 9999)
        except Exception:
            r["priority"] = 9999
        r["match_type"] = (r.get("match_type") or "contains").strip()
        cleaned.append(r)
    return sorted(cleaned, key=lambda x: x["priority"])


def _match_concept(text: str, rules: List[Dict[str, str]]) -> str:
    t = (text or "").upper()
    for r in rules:
        mt = (r.get("match_type") or "contains").lower()
        pat = (r.get("pattern") or "").upper()
        if not pat:
            continue
        if mt == "contains":
            if pat in t:
                return r["concept"]
        elif mt == "root":
            root = t.split("/", 1)[0]
            if root == pat:
                return r["concept"]
        elif mt == "regex":
            try:
                import re
                if re.search(pat, t):
                    return r["concept"]
            except Exception:
                pass
    return DEFAULT_CONCEPT


def _extract_root(full_path: str) -> str:
    fp = (full_path or "").strip()
    return fp.split("/", 1)[0] if "/" in fp else fp


def _to_int(v: str, default: int = 0) -> int:
    try:
        return int(str(v).strip())
    except Exception:
        return default


def _infer_role(name: str, pic: str, level: str, usage_reads: int, usage_writes: int, usage_conditions: int) -> str:
    n = (name or "").upper()
    p = (pic or "").upper()
    lvl = str(level or "").strip()

    if n == "FILLER":
        return "STRUCTURE"
    if usage_conditions > 0:
        return "CONTROLE"
    if "RESP" in n or "RETOUR" in n or n == "RC" or "ERR" in n:
        return "TECHNIQUE"
    if "ID" in n or "IDENT" in n or "CLE" in n or "KEY" in n:
        return "CLE_METIER"
    if lvl in ("01", "77") and not p:
        return "STRUCTURE"
    if usage_writes > 0 and usage_reads == 0:
        return "TECHNIQUE"
    return "DONNEE"


def build_structures_cartography(
    dd_global_csv: Path,
    usage_csv_dir: Path,
    rules_csv: Path,
    out_csv: Path,
) -> Path:
    """Build a structure-centric cartography enriched with concept + usage."""
    rules = _load_rules(rules_csv)

    dd_rows = _read_dict_rows(dd_global_csv, delimiter=None)

    dd_by_fp: Dict[str, Dict[str, object]] = {}

    for r in dd_rows:
        fp = (r.get("full_path") or r.get("fullpath") or r.get("path") or "").strip()
        if not fp:
            fp = (r.get("name") or "").strip()
        if not fp:
            continue

        entry = dd_by_fp.get(fp)
        if entry is None:
            entry = {
                "programs": set(),
                "section": r.get("section", ""),
                "level": r.get("level", ""),
                "name": r.get("name", ""),
                "full_path": fp,
                "pic": r.get("pic", ""),
            }
            dd_by_fp[fp] = entry

        prog = (r.get("program") or "").strip()
        if prog:
            entry["programs"].add(prog)

        if not entry.get("section") and r.get("section"):
            entry["section"] = r.get("section")
        if not entry.get("pic") and r.get("pic"):
            entry["pic"] = r.get("pic")

    usage_agg = defaultdict(lambda: {
        "programs": set(),
        "reads": 0,
        "writes": 0,
        "conditions": 0,
    })

    for usage_file in usage_csv_dir.glob("*_usage.csv"):
        usage_rows = _read_dict_rows(usage_file, delimiter=";")
        for u in usage_rows:
            fp = (u.get("variable") or u.get("full_path") or u.get("fullpath") or "").strip()
            if not fp:
                continue

            ut = (u.get("usage_type") or "").strip().lower()
            prog = (u.get("program") or "").strip()
            if prog:
                usage_agg[fp]["programs"].add(prog)

            if ut == "read":
                usage_agg[fp]["reads"] += 1
            elif ut == "write":
                usage_agg[fp]["writes"] += 1
            elif ut == "condition":
                usage_agg[fp]["conditions"] += 1

    out_csv.parent.mkdir(parents=True, exist_ok=True)

    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow([
            "structure_root",
            "section",
            "level",
            "name",
            "full_path",
            "pic",
            "concept",
            "role",
            "programs",
            "nb_programs",
            "total_reads",
            "total_writes",
            "total_conditions",
            "usage_summary",
        ])

        for fp, d in sorted(dd_by_fp.items(), key=lambda x: x[0]):
            root = _extract_root(fp)
            concept = _match_concept(fp, rules)

            u = usage_agg.get(fp, {"programs": set(), "reads": 0, "writes": 0, "conditions": 0})
            total_reads = _to_int(u.get("reads", 0))
            total_writes = _to_int(u.get("writes", 0))
            total_cond = _to_int(u.get("conditions", 0))

            programs = set(d.get("programs", set())) | set(u.get("programs", set()))
            nb_prog = len(programs)

            role = _infer_role(
                name=str(d.get("name", "")),
                pic=str(d.get("pic", "")),
                level=str(d.get("level", "")),
                usage_reads=total_reads,
                usage_writes=total_writes,
                usage_conditions=total_cond,
            )

            usage_summary = f"R={total_reads} W={total_writes} C={total_cond}"

            w.writerow([
                root,
                d.get("section", ""),
                d.get("level", ""),
                d.get("name", ""),
                fp,
                d.get("pic", ""),
                concept,
                role,
                "|".join(sorted(programs)),
                nb_prog,
                total_reads,
                total_writes,
                total_cond,
                usage_summary,
            ])

    return out_csv
