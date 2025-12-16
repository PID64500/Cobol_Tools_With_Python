#!/usr/bin/env python
import csv
from collections import Counter
from pathlib import Path

# 🔧 À ADAPTER SI BESOIN
USAGE_CSV_PATH = Path("C:/Users/Utilisateur/Documents/Workplace/cobol_tools_files/cobol_work/csv/SRSRA130_usage.csv")  

# Noms de colonnes RÉELS (d'après ton CSV)
COL_VAR_NAME = "variable"             # nom de la variable
COL_USAGE_KIND = "usage_type"         # type d'usage (lecture/écriture/etc.)
COL_PARAGRAPH = "paragraph"           # nom du paragraphe COBOL
COL_LINE = "line_etude"               # numéro de ligne dans le .etude
COL_CONTEXT = "context_usage_final"   # contexte d'utilisation


def main():
    if not USAGE_CSV_PATH.exists():
        print(f"❌ Fichier introuvable : {USAGE_CSV_PATH}")
        return

    print(f"📂 Analyse de : {USAGE_CSV_PATH}")

    total_lines = 0
    usage_kind_counter = Counter()
    var_counter = Counter()
    paragraph_counter = Counter()
    context_counter = Counter()

    with USAGE_CSV_PATH.open("r", encoding="latin-1", newline="") as f:
        reader = csv.DictReader(f)
        print(f"🧾 Colonnes détectées : {reader.fieldnames}")

        # Vérifie que les colonnes attendues existent
        for col in [COL_VAR_NAME, COL_USAGE_KIND]:
            if col not in reader.fieldnames:
                print(f"⚠ Colonne manquante dans le CSV : {col}")

        for row in reader:
            total_lines += 1

            kind = row.get(COL_USAGE_KIND, "").strip()
            usage_kind_counter[kind] += 1

            var = row.get(COL_VAR_NAME, "").strip()
            var_counter[var] += 1

            if COL_PARAGRAPH in row:
                paragraph = row.get(COL_PARAGRAPH, "").strip()
                paragraph_counter[paragraph] += 1

            if COL_CONTEXT in row:
                context = row.get(COL_CONTEXT, "").strip()
                context_counter[context] += 1

    print()
    print("════════ RÉSUMÉ GÉNÉRAL ════════")
    print(f"🔢 Nombre total de lignes dans usage.csv : {total_lines}")

    print("\n📊 Répartition par type d’usage (usage_type) :")
    for kind, count in usage_kind_counter.most_common():
        label = kind if kind else "<VIDE>"
        print(f"  - {label:30} : {count}")

    print("\n📊 Top 10 des variables les plus utilisées (tous usages confondus) :")
    for var, count in var_counter.most_common(10):
        label = var if var else "<VIDE>"
        print(f"  - {label:30} : {count}")

    print("\n📊 Top 10 des paragraphes les plus concernés :")
    for para, count in paragraph_counter.most_common(10):
        label = para if para else "<VIDE>"
        print(f"  - {label:30} : {count}")

    print("\n📊 Répartition des contextes (context_usage_final) :")
    for ctx, count in context_counter.most_common():
        label = ctx if ctx else "<VIDE>"
        print(f"  - {label:30} : {count}")


if __name__ == "__main__":
    main()
