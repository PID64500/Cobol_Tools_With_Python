import os
import sys
import csv
from collections import defaultdict


# ---------------------------------------------------------------
#  CONFIGURATION
#  (pour l'instant les CSV sont dans cobol_tools/)
# ---------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------
#  UTILITAIRES
# ---------------------------------------------------------------

def load_dd_file(dd_path):
    """
    Charge le fichier *_dd.csv.
    Retourne un dict : { variable: { 'level':..., 'pic':..., 'declared_in':... } }
    """
    data = {}
    if not os.path.exists(dd_path):
        return data

    with open(dd_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            var = row.get("variable")
            if not var:
                continue
            data[var] = {
                "level": row.get("level", "").strip(),
                "pic": row.get("pic", "").strip(),
                "declared_in": row.get("paragraph", "").strip()
            }
    return data


def load_usage_file(usage_path):
    """
    Charge le fichier *_usage.csv.
    Retourne un dict :
      usages[var] = { 'read': set(paragraphs), 'write': set(paragraphs) }
    """
    usages = defaultdict(lambda: {"read": set(), "write": set()})

    if not os.path.exists(usage_path):
        return usages

    with open(usage_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            var = row.get("variable")
            if not var:
                continue

            usage_type = row.get("usage_type", "").lower()
            paragraph = row.get("paragraph", "").strip()

            if usage_type == "read":
                usages[var]["read"].add(paragraph)
            elif usage_type == "write":
                usages[var]["write"].add(paragraph)

    return usages


def detect_categories(var, dd_info, usage_info):
    """
    Détermine la ou les catégories applicables à une variable.
    Retourne une liste de catégories détectées.
    """
    categories = []

    reads = usage_info["read"]
    writes = usage_info["write"]

    level = dd_info.get("level", "")
    is_index = (level.upper() == "INDEX")
    is_level88 = (level == "88")

    # -- Catégories générales --
    if not reads:
        categories.append("never-read")
    if not writes:
        categories.append("never-written")

    if writes and not reads:
        categories.append("write-only")
    if reads and not writes:
        categories.append("read-only")

    # -- Catégories spécifiques --
    if is_index and not reads and not writes:
        categories.append("unused-index")

    if is_level88 and not reads:
        categories.append("unused-88")

    return categories


def write_program_csv(program, rows):
    """
    Écrit le fichier PROGRAM_unused_variables.csv
    """
    out_path = os.path.join(BASE_DIR, f"{program}_unused_variables.csv")
    fieldnames = [
        "programme", "variable", "level", "pic",
        "category", "declared_in", "used_in", "usage_type"
    ]

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


# ---------------------------------------------------------------
#  MAIN LOGIC
# ---------------------------------------------------------------

def analyze_program(program):
    """
    Analyse un programme donné.
    Retourne une liste de lignes CSV pour ce programme.
    """
    dd_path = os.path.join(BASE_DIR, f"{program}_dd.csv")
    usage_path = os.path.join(BASE_DIR, f"{program}_usage.csv")

    if not os.path.exists(dd_path) or not os.path.exists(usage_path):
        print(f"[WARN] CSV manquants pour {program}, ignoré.")
        return []

    dd_data = load_dd_file(dd_path)
    usage_data = load_usage_file(usage_path)

    rows = []

    for var, dd_info in dd_data.items():
        usage_info = usage_data.get(var, {"read": set(), "write": set()})
        categories = detect_categories(var, dd_info, usage_info)

        if not categories:
            continue  # variable sans anomalies

        reads = usage_info["read"]
        writes = usage_info["write"]

        used_in = sorted(list(reads | writes))
        usage_type = (
            "none" if not used_in else
            "read" if (reads and not writes) else
            "write" if (writes and not reads) else
            "read/write"
        )

        for cat in categories:
            rows.append({
                "programme": program,
                "variable": var,
                "level": dd_info.get("level", ""),
                "pic": dd_info.get("pic", ""),
                "category": cat,
                "declared_in": dd_info.get("declared_in", ""),
                "used_in": ";".join(used_in) if used_in else "",
                "usage_type": usage_type,
            })

    return rows


def find_programs():
    """
    Détecte automatiquement tous les programmes en repérant *_dd.csv.
    """
    programs = []
    for filename in os.listdir(BASE_DIR):
        if filename.endswith("_dd.csv"):
            programs.append(filename.replace("_dd.csv", ""))
    return sorted(programs)


def write_global_csv(all_rows):
    """
    Écrit unused_variables_global.csv
    """
    out_path = os.path.join(BASE_DIR, "unused_variables_global.csv")
    fieldnames = [
        "programme", "variable", "level", "pic",
        "category", "declared_in", "used_in", "usage_type"
    ]

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in all_rows:
            writer.writerow(r)

    print(f"[OK] Fichier global généré : {out_path}")


def main():
    # Argument éventuel : programme à analyser
    if len(sys.argv) > 1:
        program = sys.argv[1].strip().upper()
        rows = analyze_program(program)
        write_program_csv(program, rows)
        write_global_csv(rows)
        return

    # Mode auto : analyse tous les programmes détectés
    programs = find_programs()
    if not programs:
        print("[ERREUR] Aucun *_dd.csv trouvé dans cobol_tools/.")
        return

    all_rows = []

    for program in programs:
        print(f"[INFO] Analyse de {program}...")
        rows = analyze_program(program)
        write_program_csv(program, rows)
        all_rows.extend(rows)

    write_global_csv(all_rows)
    print("[OK] Analyse complète terminée.")


if __name__ == "__main__":
    main()
