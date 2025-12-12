import re
import csv
import sys
from pathlib import Path

# -------------------------------------------------------------------
# CONFIG
# -------------------------------------------------------------------

# Patterns "intelligents" pour qualifier les écritures
WRITE_PATTERNS = [
    r"\bMOVE\s+.+\s+TO\s+{var}\b",
    r"\bADD\s+.+\s+TO\s+{var}\b",
    r"\bSUBTRACT\s+.+\s+FROM\s+{var}\b",
    r"\bINITIALIZE\s+{var}\b",
    r"\bSTRING\s+.+\s+INTO\s+{var}\b",
    r"\bUNSTRING\s+.+\s+INTO\s+{var}\b",
    r"\bSET\s+{var}\s+TO\b",
    r"\bSET\s+{var}\s+UP\s+BY\b",
    # EXEC CICS RESP(variable) : écriture
    r"RESP\s*\(\s*{var}\s*\)",
]

# Patterns "intelligents" pour qualifier les lectures
READ_PATTERNS = [
    r"\bIF\s+{var}\b",
    r"=+\s*{var}\b",
    r"\bEVALUATE\s+{var}\b",
    r"\b{var}\s+IN\b",
    r"\b{var}\b.*=",
    r"\b=+.*{var}\b",
    r"CALL\s+.*USING\s+.*\b{var}\b",
    r"EXEC\s+CICS\s+LINK\s+PROGRAM\s*\(\s*{var}\s*\)",
    r"EXEC\s+CICS\s+SEND\s+MAP\s*\(\s*{var}\s*\)",
    # EXEC CICS ... ITEM(variable) : lecture
    r"ITEM\s*\(\s*{var}\s*\)",
    # MOVE var TO cible : var en lecture
    r"\bMOVE\s+{var}\b\s+TO\b",
]


# -------------------------------------------------------------------
# LOADERS
# -------------------------------------------------------------------

def load_dd_file(dd_path: Path):
    """
    Charge le dictionnaire *_dd.csv et retourne une liste de variables.

    - token = nom COBOL (colonne name), utilisé pour la recherche dans le code
    - id    = identifiant dans le CSV d'usage (full_path si dispo, sinon name)
    """
    variables = []
    with dd_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("name") or "").strip()
            full_path = (row.get("full_path") or "").strip()
            if not name:
                continue
            token = name.upper()
            var_id = full_path if full_path else name
            variables.append({"id": var_id, "token": token})
    return variables


def load_paragraph_ranges(paragraphs_csv_path: Path, program: str):
    """
    Charge le fichier global paragraphs.csv et renvoie, pour un programme donné,
    une liste de plages de paragraphes :

        [
            {"start": int, "end": int, "paragraph": str},
            ...
        ]

    Colonnes dans paragraphs.csv :
        program;paragraph;start_seq;end_seq
    """
    program_upper = program.upper()
    ranges = []
    with paragraphs_csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            prog = (row.get("program") or "").strip().upper()
            if prog != program_upper:
                continue

            try:
                start_seq = int((row.get("start_seq") or "").strip())
                end_seq = int((row.get("end_seq") or "").strip())
            except ValueError:
                continue

            paragraph = (row.get("paragraph") or "").strip()
            if not paragraph:
                continue

            ranges.append(
                {
                    "start": start_seq,
                    "end": end_seq,
                    "paragraph": paragraph,
                }
            )

    ranges.sort(key=lambda r: r["start"])
    return ranges


# -------------------------------------------------------------------
# LOGIC
# -------------------------------------------------------------------

def find_paragraph_for_seq(seq: int, ranges) -> str:
    """
    Retourne le nom du paragraphe pour un numéro de séquence donné.
    """
    for r in ranges:
        if r["start"] <= seq <= r["end"]:
            return r["paragraph"]
    return "?"


def classify_usage(var_token: str, code_upper: str) -> str | None:
    """
    Essaie de classifier l'usage (read/write) dans la zone code (8–72).
    Retourne 'read', 'write' ou None si aucune pattern ne matche.
    """
    # WRITE
    for pattern in WRITE_PATTERNS:
        regex = pattern.format(var=re.escape(var_token))
        if re.search(regex, code_upper):
            return "write"

    # READ
    for pattern in READ_PATTERNS:
        regex = pattern.format(var=re.escape(var_token))
        if re.search(regex, code_upper):
            return "read"

    return None


def process_etude(program: str, variables, paragraph_ranges, etude_path: Path):
    """
    Analyse le .etude ligne par ligne et retourne la liste des usages détectés.

    Stratégie :
      - On ne regarde que la zone code (colonnes 8–72).
      - Si paragraph != "?" (on est en PROCEDURE) et que le token est présent,
        alors on compte au moins une utilisation (fallback read).
    """
    usages = []

    with etude_path.open(encoding="latin-1", errors="ignore") as f:
        for line in f:
            seq_raw = line[0:6]
            seq_stripped = seq_raw.strip()

            # Zone code COBOL : colonnes 8–72 (index 7:72)
            code_zone = line[7:72]
            code_upper = code_zone.upper()

            paragraph = "?"
            if seq_stripped.isdigit():
                seq_val = int(seq_stripped)
                paragraph = find_paragraph_for_seq(seq_val, paragraph_ranges)

            for var in variables:
                tok = var["token"]

                # Présence minimale dans la zone code
                if tok not in code_upper:
                    continue

                # Tentative de classification fine
                usage_type = classify_usage(tok, code_upper)

                # Fallback :
                # si aucune pattern ne matche mais qu'on est dans la PROCEDURE,
                # on considère au moins une lecture.
                if not usage_type and paragraph != "?":
                    usage_type = "read"

                if not usage_type:
                    continue

                usages.append(
                    {
                        "variable": var["id"],
                        "usage_type": usage_type,
                        "paragraph": paragraph,
                        "line_etude": seq_stripped,
                        "context_usage_final": line.rstrip("\n"),
                    }
                )

    return usages


def write_usage_csv(program: str, rows, csv_dir: Path):
    out_path = csv_dir / f"{program}_usage.csv"
    fieldnames = [
        "variable",
        "usage_type",
        "paragraph",
        "line_etude",
        "context_usage_final",
    ]

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


# -------------------------------------------------------------------
# MAIN (CLI standalone)
# -------------------------------------------------------------------

def main():
    """
    Mode autonome :
      python scan_variable_usage.py SRSRA130 --work-dir <work_dir>
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Scan des usages de variables COBOL à partir du dictionnaire *_dd.csv et du paragraphs.csv global."
    )
    parser.add_argument("program", help="Nom du programme COBOL (ex: SRSTC0, SRSTA0, ...)")
    parser.add_argument(
        "--work-dir",
        default=".",
        help="Répertoire de travail contenant 'etude' et 'csv' (défaut: répertoire courant).",
    )

    args = parser.parse_args()

    program = args.program.strip().upper()
    work_dir = Path(args.work_dir).resolve()
    etude_dir = work_dir / "etude"
    csv_dir = work_dir / "csv"

    dd_path = csv_dir / f"{program}_dd.csv"
    paragraphs_csv = csv_dir / "paragraphs.csv"

    etude_candidates = [
        etude_dir / f"{program}.cbl.etude",
        etude_dir / f"{program}.CBL.etude",
        etude_dir / f"{program}.cob.etude",
        etude_dir / f"{program}.COB.etude",
        etude_dir / f"{program}.etude",
    ]
    etude_path = None
    for candidate in etude_candidates:
        if candidate.exists():
            etude_path = candidate
            break

    if etude_path is None:
        print(f"[ERREUR] Fichier .etude introuvable pour {program} dans {etude_dir}")
        sys.exit(1)

    if not dd_path.exists():
        print(f"[ERREUR] Fichier dictionnaire manquant : {dd_path}")
        sys.exit(1)

    if not paragraphs_csv.exists():
        print(f"[ERREUR] Fichier paragraphs.csv manquant : {paragraphs_csv}")
        sys.exit(1)

    print(f"[INFO] Variables depuis {dd_path}")
    variables = load_dd_file(dd_path)

    print(f"[INFO] Paragraphes depuis {paragraphs_csv} (programme={program})")
    paragraph_ranges = load_paragraph_ranges(paragraphs_csv, program)

    print(f"[INFO] Analyse de {etude_path}")
    usages = process_etude(program, variables, paragraph_ranges, etude_path)

    write_usage_csv(program, usages, csv_dir)
    print(f"[OK] Fichier généré : {csv_dir / (program + '_usage.csv')}")


if __name__ == "__main__":
    main()
