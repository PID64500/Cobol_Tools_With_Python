#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
scan_copies.py

Phase d'observation : scanne les programmes COBOL pour extraire
toutes les phrases COPY (y compris multi-lignes) et les loggue
dans un CSV.

Usage :
    python scan_copies.py chemin/vers/fichier.cbl
    python scan_copies.py chemin/vers/repertoire

Options :
    --out copies_trouves.csv  (nom du fichier de sortie)
"""

import argparse
import csv
import re
from pathlib import Path
from typing import List, Tuple, Iterable


def is_comment_line(line: str) -> bool:
    """Ligne commentaire COBOL : '*' en colonne 7."""
    return len(line) >= 7 and line[6] == "*"


def iter_copy_statements(lines: List[str]) -> Iterable[Tuple[int, str]]:
    """
    Retourne des tuples (line_start, statement) pour chaque phrase COPY trouvée.
    Gère les phrases sur plusieurs lignes en concaténant jusqu'au '.' final.
    """
    in_copy = False
    buffer = ""
    start_line = 0

    for idx, raw in enumerate(lines, start=1):
        line = raw.rstrip("\n")

        if is_comment_line(line):
            continue

        # Zone code approximative : colonnes 8-72 (index 7:)
        if len(line) > 7:
            code = line[7:72]  # on coupe avant la zone 73-80
        else:
            code = ""

        if not in_copy:
            # On cherche un COPY dans la ligne
            if re.search(r"\bCOPY\b", code, re.IGNORECASE):
                in_copy = True
                start_line = idx
                buffer = code.strip()

                # Si on voit déjà un point dans la phrase : fin de statement
                if "." in code:
                    yield start_line, buffer
                    in_copy = False
                    buffer = ""
                    start_line = 0
        else:
            # On continue la phrase COPY
            buffer += " " + code.strip()
            if "." in code:
                # Fin de phrase
                yield start_line, buffer
                in_copy = False
                buffer = ""
                start_line = 0

    # Si on termine le fichier en plein milieu d'un COPY : on log quand même
    if in_copy and buffer:
        yield start_line, buffer


def parse_copy_info(statement: str) -> Tuple[str, bool]:
    """
    Extrait le nom du copybook et la présence d'un REPLACING.
    statement est la phrase COPY complète (zone code concaténée).
    """
    upper = statement.upper()
    m = re.search(r"\bCOPY\s+([A-Z0-9-]+)", upper)
    copybook = m.group(1) if m else ""
    has_replacing = "REPLACING" in upper
    return copybook, has_replacing


def scan_file(path: Path) -> List[dict]:
    """
    Scanne un fichier COBOL et retourne une liste de dicts
    décrivant les COPY trouvés.
    """
    rows: List[dict] = []
    with path.open("r", encoding="latin-1", errors="ignore") as f:
        lines = f.readlines()

    program = path.stem  # ex: SRSTC0 à partir de SRSTC0.cbl

    for line_start, stmt in iter_copy_statements(lines):
        copybook, has_replacing = parse_copy_info(stmt)
        rows.append(
            {
                "program": program,
                "file": str(path),
                "line_start": line_start,
                "copybook": copybook,
                "has_replacing": "YES" if has_replacing else "NO",
                "statement": " ".join(stmt.split()),  # normalisation espaces
            }
        )
    return rows


def find_cobol_files(root: Path) -> Iterable[Path]:
    """
    Si root est un fichier -> le renvoie.
    Si c'est un répertoire -> parcourt récursivement les .cbl, .CBL, .cob, .COB.
    """
    if root.is_file():
        yield root
    else:
        exts = {".cbl", ".CBL", ".cob", ".COB"}
        for p in root.rglob("*"):
            if p.is_file() and p.suffix in exts:
                yield p


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan des COPY COBOL")
    parser.add_argument("path", help="Fichier COBOL ou répertoire à analyser")
    parser.add_argument(
        "--out",
        default="copies_trouves.csv",
        help="Fichier CSV de sortie (défaut: copies_trouves.csv)",
    )
    args = parser.parse_args()

    root = Path(args.path)
    if not root.exists():
        print(f"[ERREUR] Chemin introuvable : {root}")
        return 1

    all_rows: List[dict] = []

    for cob_file in find_cobol_files(root):
        print(f"[INFO] Scan {cob_file}")
        rows = scan_file(cob_file)
        all_rows.extend(rows)

    if not all_rows:
        print("[INFO] Aucun COPY trouvé.")
        return 0

    out_path = Path(args.out)
    with out_path.open("w", newline="", encoding="utf-8") as csvfile:
        fieldnames = ["program", "file", "line_start", "copybook", "has_replacing", "statement"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"[INFO] {len(all_rows)} COPY trouvés. Résultat : {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
