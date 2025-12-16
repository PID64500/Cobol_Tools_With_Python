# scripts/data/data_concepts_usage.py

import csv
from pathlib import Path
from collections import defaultdict


def load_rules(rules_csv: Path):
    rules = []
    with rules_csv.open(encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for r in reader:
            r["priority"] = int(r["priority"])
            rules.append(r)
    return sorted(rules, key=lambda x: x["priority"])


def match_concept(full_path: str, rules: list[str]) -> str:
    name = full_path.upper()
    for r in rules:
        pattern = r["pattern"].upper()
        if r["match_type"] == "contains" and pattern in name:
            return r["concept"]
    return "TECHNIQUE_CONTROLE"  # défaut volontaire


def extract_root(full_path: str) -> str:
    return full_path.split("/")[0] if "/" in full_path else full_path


def build_data_concepts_usage(
    dd_global_csv: Path,
    usage_csv_dir: Path,
    rules_csv: Path,
    out_csv: Path,
):
    rules = load_rules(rules_csv)

    # --- Dictionnaire global ---
    dd = {}
    with dd_global_csv.open(encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for r in reader:
            dd[r["full_path"]] = r

    # --- Usages ---
    usage_agg = defaultdict(lambda: {
        "programs": set(),
        "usage_types": set(),
        "reads": 0,
        "writes": 0,
        "conditions": 0,
    })

    for usage_file in usage_csv_dir.glob("*_usage.csv"):
        with usage_file.open(encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=";")
            for r in reader:
                fp = r["variable"]
                u = r["usage_type"].lower()
                usage_agg[fp]["programs"].add(r["program"])
                usage_agg[fp]["usage_types"].add(u)
                if u == "read":
                    usage_agg[fp]["reads"] += 1
                elif u == "write":
                    usage_agg[fp]["writes"] += 1
                elif u == "condition":
                    usage_agg[fp]["conditions"] += 1

    # --- Sortie ---
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    with out_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow([
            "concept",
            "variable_root",
            "full_path",
            "pic",
            "programs",
            "usage_types",
            "nb_programs",
            "total_reads",
            "total_writes",
            "total_conditions",
            "risk_indicator",
            "notes",
        ])

        for full_path, usage in usage_agg.items():
            dd_row = dd.get(full_path, {})
            concept = match_concept(full_path, rules)
            nb_prog = len(usage["programs"])

            if nb_prog >= 3 and usage["writes"] > 0:
                risk = "HIGH"
            elif nb_prog >= 2:
                risk = "MEDIUM"
            else:
                risk = "LOW"

            writer.writerow([
                concept,
                extract_root(full_path),
                full_path,
                dd_row.get("pic", ""),
                "|".join(sorted(usage["programs"])),
                "|".join(sorted(usage["usage_types"])),
                nb_prog,
                usage["reads"],
                usage["writes"],
                usage["conditions"],
                risk,
                "",
            ])
