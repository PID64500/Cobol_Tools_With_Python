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
from typing import List, Dict, Any
from pathlib import Path
import logging
logger = logging.getLogger(__name__)


@dataclass
class Paragraph:
    order: int   # ordre de rencontre
    seq: str     # numero de sequence (000123)
    name: str    # nom du paragraphe (100-INITIALISATION)


def is_paragraph_line(line: str) -> bool:
    """
    Règle unifiée de détection de paragraphe COBOL sur une ligne .cbl.etude.

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

def extract_from_files(files: List[Any]) -> Dict[str, List[Paragraph]]:
    """
    Wrapper haut niveau :
    - accepte :
        * une liste de chemins (str ou Path)
          ex: ["./SRSTAB.cbl.etude", Path("./SRSRRET.cbl.etude")]
        * une liste de dictionnaires décrivant les fichiers normalisés
          ex: [{"etude_path": "./SRSTAB.cbl.etude", ...}, {...}, ...]

    Retourne un dict :
      { chemin_fichier(str) : [Paragraph, ...] }
    """
    result: Dict[str, List[Paragraph]] = {}

    for f in files:
        etude_path_str: str

        # Cas 1 : f est déjà un chemin (str ou Path)
        if isinstance(f, (str, Path)):
            etude_path_str = str(f)

        # Cas 2 : f est un dict -> on essaie de trouver une clé de chemin
        elif isinstance(f, dict):
            possible_keys = ["etude_path", "normalized_path", "path", "file", "filename"]
            path_value = None

            for key in possible_keys:
                if key in f and f[key]:
                    path_value = f[key]
                    break

            if path_value is None:
                raise KeyError(
                    f"Aucune clé de chemin trouvée dans l'entrée : {f}. "
                    f"Adapte 'possible_keys' dans extract_from_files()."
                )

            etude_path_str = str(path_value)

        else:
            raise TypeError(
                f"Type inattendu dans files : {type(f)}. "
                f"Attendu str, pathlib.Path ou dict."
            )

        # Maintenant on est sûr d'avoir un chemin texte
        paragraphs = extract_paragraphs(etude_path_str)
        result[etude_path_str] = paragraphs

    return result

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
