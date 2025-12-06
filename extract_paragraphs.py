#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
extract_paragraphs.py
---------------------
A partir d'un fichier COBOL normalise (.cbl.etude),
extrait la table des paragraphes (labels en colonne 8),
UNIQUEMENT APRES 'PROCEDURE DIVISION.'.

Usage :
    python extract_paragraphs.py chemin\MONPROG.cbl.etude
"""

import sys
import os
from dataclasses import dataclass
from typing import List


@dataclass
class Paragraph:
    order: int   # ordre de rencontre
    seq: str     # numero de sequence (000123)
    name: str    # nom du paragraphe (100-INITIALISATION)


def is_paragraph_line(line: str) -> bool:
    """
    Determine si une ligne .etude contient un debut de paragraphe.

    Format normalise :
      - colonnes 1-6 : sequence numerique
      - colonnes 7-72 : code COBOL
      - colonnes 73-80 : espaces

    On considere "paragraphe" si :
      - col 8 (index 7) n'est pas un espace
      - premier token se termine par un point (ex: 100-INITIALISATION.)
    """
    if len(line) < 8:
        return False

    # colonne 8
    if line[7] == " ":
        return False

    code = line[7:72].rstrip()
    if not code:
        return False

    first_token = code.split()[0]
    if not first_token.endswith("."):
        return False

    return True


def extract_paragraphs(etude_path: str) -> List[Paragraph]:
    """
    Lit un fichier .cbl.etude et renvoie la liste des paragraphes detectes,
    UNIQUEMENT APRES 'PROCEDURE DIVISION.'.
    """
    if not os.path.exists(etude_path):
        raise FileNotFoundError(f"Fichier introuvable : {etude_path}")

    paragraphs: List[Paragraph] = []
    order = 1
    in_procedure_division = False

    with open(etude_path, "r", encoding="latin-1", errors="ignore") as f:
        for raw in f:
            line = raw.rstrip("\n")

            if len(line) < 72:
                line = line.ljust(72)

            # Detecter la ligne 'PROCEDURE DIVISION.'
            code = line[7:72].strip()
            if code.upper().startswith("PROCEDURE DIVISION"):
                in_procedure_division = True
                # On ne la considere pas comme paragraphe
                continue

            # Tant qu'on n'est pas dans la PROCEDURE DIVISION, on ne cherche pas de paragraphes
            if not in_procedure_division:
                continue

            if not is_paragraph_line(line):
                continue

            seq = line[0:6]
            code = line[7:72].rstrip()
            first_token = code.split()[0]
            name = first_token.rstrip(".")

            paragraphs.append(Paragraph(order=order, seq=seq, name=name))
            order += 1

    return paragraphs


def print_paragraph_table(paragraphs: List[Paragraph], etude_path: str) -> None:
    prog_name = os.path.basename(etude_path)

    print(f"# Table des paragraphes pour : {prog_name}\n")
    print("Ordre     Seq  Nom")
    print("----------------------------------------")

    if not paragraphs:
        print("   (aucun paragraphe detecte)")
        return

    for p in paragraphs:
        print(f"{p.order:5d}  {p.seq}  {p.name}")


def main():
    if len(sys.argv) != 2:
        print("Usage : python extract_paragraphs.py <fichier.cbl.etude>")
        sys.exit(1)

    etude_path = sys.argv[1]

    try:
        paragraphs = extract_paragraphs(etude_path)
        print_paragraph_table(paragraphs, etude_path)
    except Exception as e:
        print(f"[ERREUR] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
