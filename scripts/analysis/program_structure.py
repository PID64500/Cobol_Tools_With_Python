#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
program_structure.py
--------------------

À partir des fichiers COBOL normalisés (.etude), construit la structure
des programmes sous forme d'un CSV unique :

    <work_dir>/csv/program_structure.csv

Structure de sortie (séparateur ';') :

    programme ; proc ; deb_proc ; fin_proc

- programme : nom du programme (basename sans suffixes .cbl.etude, .etude, etc.)
- proc      : nom du paragraphe
- deb_proc  : n° de séquence (col. 1-6) de la ligne du paragraphe
- fin_proc  : n° de séquence de la dernière ligne appartenant à ce paragraphe

Ce fichier servira de "dimension" centrale pour plugger :
    - program_structure_detail_data
    - program_structure_detail_exec
    - program_structure_detail_...

Usage :

    python program_structure.py <work_dir>

Ce script lit :

    <work_dir>/etude/*.etude

et écrit :

    <work_dir>/csv/program_structure.csv
"""

import csv
import logging
import sys
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Logging de base
# ---------------------------------------------------------------------------

def setup_basic_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


# ---------------------------------------------------------------------------
# Détection d'une ligne de paragraphe
# (logique cohérente avec extract_paragraphs.py)
# ---------------------------------------------------------------------------

def is_paragraph_line(line: str) -> bool:
    """
    Règle unifiée de détection de paragraphe COBOL sur une ligne .etude.

    On considère qu'il s'agit d'un paragraphe si :
      - la ligne fait au moins 8 colonnes,
      - la colonne 7 (index 6) n'est pas '*',
      - la colonne 8 (index 7) n'est pas un espace,
      - la zone code (cols 8-72) ne contient qu'un seul token,
      - ce token se termine par un point,
      - le nom de paragraphe (sans le point final) fait 1 à 30 caractères,
      - il ne contient que lettres/chiffres/tirets,
      - il commence par une lettre ou un chiffre.
    """
    if len(line) < 8:
        return False

    # Colonne 7 = index 6 : si '*', c'est un commentaire
    if line[6] == "*":
        return False

    # Colonne 8 = index 7 : doit être non vide
    if line[7] == " ":
        return False

    code = line[7:72].rstrip()
    if not code:
        return False

    tokens = code.split()
    # On veut exactement un seul mot sur la ligne
    if len(tokens) != 1:
        return False

    token = tokens[0]
    if not token.endswith("."):
        return False

    name = token[:-1]  # sans le point final
    if not (1 <= len(name) <= 30):
        return False

    upper = name.upper()

    # Premier caractère : lettre ou chiffre
    if not upper[0].isalnum():
        return False

    # Tous les caractères : lettre, chiffre ou tiret
    for ch in upper:
        if not (ch.isalnum() or ch == "-"):
            return False

    return True


# ---------------------------------------------------------------------------
# Extraction de la structure d'un programme
# ---------------------------------------------------------------------------

def detect_paragraphs_in_etude(etude_path: Path) -> List[Dict[str, str]]:
    """
    Analyse un fichier .etude et renvoie une liste de dict :

      {
        "programme": <nom du programme>,
        "proc": <nom du paragraphe>,
        "deb_proc": <seq début>,
        "fin_proc": <seq fin>
      }

    Les paragraphes sont détectés uniquement après 'PROCEDURE DIVISION'.
    """
    paragraphs: List[Dict[str, str]] = []

    if not etude_path.exists():
        logger.warning("Fichier introuvable : %s", etude_path)
        return paragraphs

    try:
        lines = etude_path.read_text(encoding="latin-1", errors="ignore").splitlines()
    except Exception as e:
        logger.error("Erreur de lecture %s : %s", etude_path, e)
        return paragraphs

    if not lines:
        return paragraphs

    # Nom du programme = basename sans suffixes .cbl.etude / .etude
    prog_name = etude_path.name
    for suffix in [".cbl.etude", ".CBL.ETUDE", ".etude", ".ETUDE"]:
        if prog_name.endswith(suffix):
            prog_name = prog_name[: -len(suffix)]
            break

    in_procedure_division = False

    # Liste brute : [(name, start_seq)]
    raw_paragraphs: List[Dict[str, str]] = []

    last_seq_in_file: Optional[str] = None

    # Première passe : repérer PROCEDURE DIVISION, les paragraphes et le dernier seq du fichier
    for raw in lines:
        line = raw.rstrip("\n")

        # Normaliser la longueur à 72 colonnes minimum
        if len(line) < 72:
            line = line.ljust(72)

        seq = line[0:6]
        if seq.strip().isdigit():
            last_seq_in_file = seq

        code = line[7:72].strip()

        # Détection de la PROCEDURE DIVISION
        if code.upper().startswith("PROCEDURE DIVISION"):
            in_procedure_division = True
            continue

        if not in_procedure_division:
            continue

        if not is_paragraph_line(line):
            continue

        # C'est une ligne de paragraphe
        code = line[7:72].rstrip()
        first_token = code.split()[0]
        name = first_token.rstrip(".")

        raw_paragraphs.append({"name": name, "start_seq": seq})

    if not raw_paragraphs:
        return paragraphs

    # Si on n'a pas de dernier seq global, on se rabat sur le dernier start_seq
    if last_seq_in_file is None:
        last_seq_in_file = raw_paragraphs[-1]["start_seq"]

    # Deuxième passe : calcul des fin_proc
    for idx, p in enumerate(raw_paragraphs):
        deb = p["start_seq"]
        name = p["name"]

        if idx + 1 < len(raw_paragraphs):
            # fin = seq précédent le paragraphe suivant, si possible
            next_seq = raw_paragraphs[idx + 1]["start_seq"]
            fin = next_seq
            # Si les numéros sont numériques, on peut faire -1
            if deb.strip().isdigit() and next_seq.strip().isdigit():
                fin_int = int(next_seq) - 1
                if fin_int < int(deb):
                    fin_int = int(deb)
                fin = f"{fin_int:06d}"
        else:
            # Dernier paragraphe : s'étend jusqu'au dernier numéro de séquence connu
            fin = last_seq_in_file or deb

        paragraphs.append(
            {
                "programme": prog_name,
                "proc": name,
                "deb_proc": deb,
                "fin_proc": fin,
            }
        )

    return paragraphs


# ---------------------------------------------------------------------------
# Génération du CSV central program_structure.csv
# ---------------------------------------------------------------------------

def generate_program_structure(work_dir: Path) -> Path:
    """
    Parcourt <work_dir>/etude/*.etude et génère
        <work_dir>/csv/program_structure.csv

    Retourne le chemin du CSV.
    """
    etude_dir = work_dir / "etude"
    csv_dir = work_dir / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)

    output_path = csv_dir / "program_structure.csv"

    if not etude_dir.exists():
        logger.error("Répertoire etude inexistant : %s", etude_dir)
        return output_path

    all_rows: List[Dict[str, str]] = []

    etude_files = sorted(etude_dir.glob("*.etude"))
    if not etude_files:
        logger.warning("Aucun fichier .etude trouvé dans %s", etude_dir)

    for etude_path in etude_files:
        logger.info("Analyse de %s", etude_path.name)
        rows = detect_paragraphs_in_etude(etude_path)
        all_rows.extend(rows)

    # Tri pour stabilité : par programme puis déb_proc
    all_rows.sort(key=lambda r: (r["programme"], r["deb_proc"]))

    # Écriture du CSV ; séparateur ';'
    fieldnames = ["programme", "proc", "deb_proc", "fin_proc"]

    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        for row in all_rows:
            writer.writerow(row)

    logger.info("program_structure.csv généré : %s", output_path)
    return output_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if len(argv) != 1:
        print("Usage : python program_structure.py <work_dir>")
        return 1

    work_dir = Path(argv[0]).resolve()
    logger.info("work_dir = %s", work_dir)

    generate_program_structure(work_dir)
    return 0


if __name__ == "__main__":
    setup_basic_logging("INFO")
    raise SystemExit(main())
