#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
generate_paragraphs_csv.py
--------------------------

Script autonome pour extraire tous les paragraphes COBOL à partir des fichiers
normalisés (.etude) et produire un CSV central.

Règles pour reconnaître un paragraphe :

1. On ne commence à chercher des paragraphes qu’après avoir trouvé une ligne
   contenant "PROCEDURE DIVISION".
2. Colonne 7 (index 6) doit être différente de '*'.
3. La zone code est définie comme les colonnes 8–72 : line[7:72].
4. Un paragraphe est une ligne où :
   - la zone code commence OBLIGATOIREMENT en colonne 8 (line[7] != ' ')
   - on trouve un '.' dans la zone code
   - la partie avant ce '.' :
       * ne contient aucun espace
       * a une longueur 1 <= n <= 30
   → cette partie est le nom du paragraphe.

Le script produit un CSV avec les colonnes :
    program,paragraph,start_seq,end_seq

- program   : nom du programme (basename sans .cbl.etude / .etude, etc.)
- paragraph : nom du paragraphe
- start_seq : numéro de séquence (col. 1–6) de la ligne du paragraphe
- end_seq   : numéro de séquence de la dernière ligne appartenant à ce paragraphe

Usage :

    python generate_paragraphs_csv.py <work_dir>

Cela lit :
    <work_dir>/etude/*.etude
et écrit :
    <work_dir>/csv/paragraphs.csv
"""

import csv
import logging
import os
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


def _setup_basic_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


# ---------------------------------------------------------------------------
# Détection des paragraphes dans un fichier .etude
# ---------------------------------------------------------------------------

def detect_paragraphs_in_etude(etude_path: Path) -> List[Dict[str, str]]:
    """
    Analyse un fichier .etude et renvoie une liste de dicts :

        {
            "program": <nom du programme>,
            "paragraph": <nom du paragraphe>,
            "start_seq": <numéro de séquence départ>,
            "end_seq": <numéro de séquence fin>,
        }
    """
    paragraphs: List[Dict[str, str]] = []

    # Nom du programme = basename sans extension .cbl.etude, .CBL.etude, etc.
    base = etude_path.name
    program = base
    for ext in (".cbl.etude", ".CBL.etude", ".cob.etude", ".COB.etude", ".etude"):
        if base.endswith(ext):
            program = base[: -len(ext)]
            break

    try:
        lines = etude_path.read_text(encoding="latin-1", errors="ignore").splitlines()
    except Exception as e:
        logger.error("Erreur de lecture %s : %s", etude_path, e)
        return paragraphs

    in_procedure_division = False

    current_name: Optional[str] = None
    current_start_seq: Optional[str] = None
    current_end_seq: Optional[str] = None

    def close_current_paragraph() -> None:
        nonlocal current_name, current_start_seq, current_end_seq
        if current_name and current_start_seq and current_end_seq:
            paragraphs.append(
                {
                    "program": program,
                    "paragraph": current_name,
                    "start_seq": current_start_seq,
                    "end_seq": current_end_seq,
                }
            )
        current_name = None
        current_start_seq = None
        current_end_seq = None

    for line in lines:
        # Numéro de séquence (colonnes 1–6)
        seq_raw = line[0:6] if len(line) >= 6 else ""
        seq_stripped = seq_raw.strip()
        seq_value = seq_stripped if seq_stripped.isdigit() else None

        # Détection de PROCEDURE DIVISION (en pratique dans la zone code)
        code_area_full = line[7:72] if len(line) >= 72 else line[7:]
        if "PROCEDURE DIVISION" in code_area_full.upper():
            in_procedure_division = True
            close_current_paragraph()
            continue

        if not in_procedure_division:
            # On ignore tout ce qui est avant PROCEDURE DIVISION
            continue

        if len(line) < 8:
            # Trop court pour contenir une zone code exploitable
            continue

        # Colonne 7 : commentaire ?
        indicator = line[6]  # index 6 = col 7
        if indicator == "*":
            # Commentaire, on ne le compte pas dans les paragraphes
            continue

        # Zone code = colonnes 8–72
        code_area = line[7:72]

        # Règle 4 : doit commencer OBLIGATOIREMENT en col 8 (pas d'espace au début)
        if not code_area or code_area[0] == " ":
            # Code indenté → pas un nom de paragraphe
            if current_name and seq_value is not None:
                current_end_seq = seq_value
            continue

        # On cherche le premier '.'
        dot_index = code_area.find(".")
        if dot_index == -1:
            # Pas de '.', donc pas un label de paragraphe
            if current_name and seq_value is not None:
                current_end_seq = seq_value
            continue

        # Partie avant le '.' (nom candidat)
        name_part = code_area[:dot_index]
        name_stripped = name_part.strip()

        # Il ne doit y avoir aucun espace dans le nom
        if " " in name_stripped:
            # C'est une instruction (MOVE TRUC. etc.), pas un paragraphe
            if current_name and seq_value is not None:
                current_end_seq = seq_value
            continue

        # Longueur 1..30
        if not (1 <= len(name_stripped) <= 30):
            if current_name and seq_value is not None:
                current_end_seq = seq_value
            continue

        # Si on arrive ici, c'est un NOUVEAU paragraphe
        # On clôt l'éventuel paragraphe en cours
        close_current_paragraph()

        current_name = name_stripped
        current_start_seq = seq_value or ""
        current_end_seq = seq_value or ""

    # Fin de fichier : clôture du dernier paragraphe éventuel
    close_current_paragraph()

    return paragraphs


# ---------------------------------------------------------------------------
# Construction du CSV central
# ---------------------------------------------------------------------------

def generate_paragraphs_csv_from_etude_dir(etude_dir: Path, csv_path: Path) -> None:
    """
    Parcourt tous les fichiers *.etude dans etude_dir et écrit un CSV central
    avec les paragraphes détectés.

    :param etude_dir: Répertoire contenant les .etude
    :param csv_path:  Chemin du CSV de sortie
    """
    if not etude_dir.is_dir():
        raise FileNotFoundError(f"Répertoire .etude introuvable : {etude_dir}")

    all_rows: List[Dict[str, str]] = []

    for etude_file in sorted(etude_dir.glob("*.etude")):
        logger.info("Analyse des paragraphes dans %s", etude_file)
        rows = detect_paragraphs_in_etude(etude_file)
        all_rows.extend(rows)

    csv_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = ["program", "paragraph", "start_seq", "end_seq"]

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        for row in all_rows:
            writer.writerow(row)

    logger.info("CSV paragraphes généré : %s (%d lignes)", csv_path, len(all_rows))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main_cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Génère un CSV central avec tous les paragraphes COBOL à partir des fichiers .etude."
    )
    parser.add_argument(
        "work_dir",
        help="Répertoire de travail (contenant le sous-répertoire 'etude')",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Niveau de log (DEBUG, INFO, WARNING, ERROR)",
    )

    args = parser.parse_args()
    _setup_basic_logging(args.log_level)

    work_dir = Path(args.work_dir).resolve()
    etude_dir = work_dir / "etude"
    csv_dir = work_dir / "csv"
    csv_path = csv_dir / "paragraphs.csv"

    generate_paragraphs_csv_from_etude_dir(etude_dir, csv_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
