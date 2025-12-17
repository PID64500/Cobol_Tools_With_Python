# scripts/data/concepts_consolidation.py
from __future__ import annotations

import csv
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple, Optional


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


def _to_int(v: str, default: int = 0) -> int:
    try:
        return int(str(v).strip())
    except Exception:
        return default


def _split_programs(programs_field: str) -> List[str]:
    if not programs_field:
        return []
    # our format uses '|'
    return [p.strip() for p in programs_field.split("|") if p.strip()]


def build_concepts_consolidation(
    structures_cartography_csv: Path,
    out_dir: Path,
    top_n: int = 25,
) -> Dict[str, Path]:
    """Build Niveau 2.C consolidation deliverables from structures_cartography.csv.

    Inputs
    - structures_cartography_csv: produced by structures_cartography.py (semicolon)
    Outputs (in out_dir)
    - concepts_summary.csv
    - concepts_by_program.csv
    - top_transversal_structures.csv
    Returns dict of generated paths.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = _read_dict_rows(structures_cartography_csv, delimiter=None)

    # ---- Aggregations
    # concept -> stats
    c_stats = defaultdict(lambda: {
        "structures": 0,
        "roots": set(),
        "programs": set(),
        "reads": 0,
        "writes": 0,
        "conditions": 0,
    })

    # program -> concept -> stats
    pc_stats = defaultdict(lambda: defaultdict(lambda: {
        "structures": 0,
        "reads": 0,
        "writes": 0,
        "conditions": 0,
    }))

    # structures transversal (full_path)
    s_stats = defaultdict(lambda: {
        "concept": "",
        "role": "",
        "section": "",
        "root": "",
        "programs": set(),
        "reads": 0,
        "writes": 0,
        "conditions": 0,
    })

    for r in rows:
        concept = (r.get("concept") or "").strip() or "UNDEFINED"
        role = (r.get("role") or "").strip()
        section = (r.get("section") or "").strip()
        root = (r.get("structure_root") or "").strip()
        fp = (r.get("full_path") or "").strip()
        if not fp:
            continue

        progs = set(_split_programs(r.get("programs") or ""))
        reads = _to_int(r.get("total_reads") or 0)
        writes = _to_int(r.get("total_writes") or 0)
        cond = _to_int(r.get("total_conditions") or 0)

        # concept stats
        c_stats[concept]["structures"] += 1
        if root:
            c_stats[concept]["roots"].add(root)
        c_stats[concept]["programs"].update(progs)
        c_stats[concept]["reads"] += reads
        c_stats[concept]["writes"] += writes
        c_stats[concept]["conditions"] += cond

        # per program stats
        for p in progs:
            pc = pc_stats[p][concept]
            pc["structures"] += 1
            pc["reads"] += reads
            pc["writes"] += writes
            pc["conditions"] += cond

        # structure stats
        ss = s_stats[fp]
        if not ss["concept"]:
            ss["concept"] = concept
        if not ss["role"]:
            ss["role"] = role
        if not ss["section"]:
            ss["section"] = section
        if not ss["root"]:
            ss["root"] = root
        ss["programs"].update(progs)
        ss["reads"] += reads
        ss["writes"] += writes
        ss["conditions"] += cond

    # ---- 1) concepts_summary.csv
    concepts_summary = out_dir / "concepts_summary.csv"
    with concepts_summary.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow([
            "concept",
            "nb_structures",
            "nb_roots",
            "nb_programs",
            "total_reads",
            "total_writes",
            "total_conditions",
            "intensity_score",
            "notes",
        ])
        # intensity: simple weighted score
        def score(cs):
            return (cs["reads"] + 2*cs["writes"] + 3*cs["conditions"])
        for concept, cs in sorted(c_stats.items(), key=lambda kv: score(kv[1]), reverse=True):
            w.writerow([
                concept,
                cs["structures"],
                len(cs["roots"]),
                len(cs["programs"]),
                cs["reads"],
                cs["writes"],
                cs["conditions"],
                score(cs),
                "",
            ])

    # ---- 2) concepts_by_program.csv
    concepts_by_program = out_dir / "concepts_by_program.csv"
    with concepts_by_program.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow([
            "program",
            "concept",
            "nb_structures",
            "total_reads",
            "total_writes",
            "total_conditions",
            "intensity_score",
        ])
        for program in sorted(pc_stats.keys()):
            per = pc_stats[program]
            def pscore(d):
                return (d["reads"] + 2*d["writes"] + 3*d["conditions"])
            for concept, d in sorted(per.items(), key=lambda kv: pscore(kv[1]), reverse=True):
                w.writerow([
                    program,
                    concept,
                    d["structures"],
                    d["reads"],
                    d["writes"],
                    d["conditions"],
                    pscore(d),
                ])

    # ---- 3) top_transversal_structures.csv
    top_structures = out_dir / "top_transversal_structures.csv"
    with top_structures.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow([
            "rank",
            "full_path",
            "structure_root",
            "section",
            "concept",
            "role",
            "nb_programs",
            "programs",
            "total_reads",
            "total_writes",
            "total_conditions",
            "intensity_score",
        ])
        def sscore(ss):
            return (len(ss["programs"]), ss["reads"] + 2*ss["writes"] + 3*ss["conditions"])
        # sort: most programs first, then intensity
        sorted_items = sorted(s_stats.items(), key=lambda kv: (sscore(kv[1])[0], sscore(kv[1])[1]), reverse=True)
        for idx, (fp, ss) in enumerate(sorted_items[:max(1, top_n)], start=1):
            intensity = ss["reads"] + 2*ss["writes"] + 3*ss["conditions"]
            w.writerow([
                idx,
                fp,
                ss["root"],
                ss["section"],
                ss["concept"],
                ss["role"],
                len(ss["programs"]),
                "|".join(sorted(ss["programs"])),
                ss["reads"],
                ss["writes"],
                ss["conditions"],
                intensity,
            ])

    return {
        "concepts_summary": concepts_summary,
        "concepts_by_program": concepts_by_program,
        "top_transversal_structures": top_structures,
    }
