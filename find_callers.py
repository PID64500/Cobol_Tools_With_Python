#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
find_callers.py
---------------
A partir d'un fichier COBOL normalise (.cbl.etude),
pour chaque paragraphe, recherche les lignes qui font
  - GO TO <paragraphe>
  - PERFORM <paragraphe>

Usage :
    python find_callers.py chemin\MONPROG.cbl.etude

Sortie texte sur stdout.
"""

import sys
import os
from dataclasses import dataclass
from typing import List, Dict


# --- Reprise de la logique d'extraction des paragraphes --- #

@dataclass
class Paragraph:
    order: int
    seq: str
    name: str


def is_paragraph_line(line: str) -> bool:
    if len(line) < 8:
        return False

    # col 8 (index 7) doit être non blanc
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

            code = line[7:72].strip()

            # Detecter PROCEDURE DIVISION
            if code.upper().startswith("PROCEDURE DIVISION"):
                in_procedure_division = True
                continue

            if not in_procedure_division:
                continue

            if not is_paragraph_line(line):
                continue

            seq = line[0:6]
            first_token = code.split()[0]
            name = first_token.rstrip(".")

            paragraphs.append(Paragraph(order=order, seq=seq, name=name))
            order += 1

    return paragraphs


# --- Recherche des GO TO / PERFORM --- #

@dataclass
class Caller:
    seq: str        # sequence de la ligne appelante
    call_type: str  # "GO TO" ou "PERFORM"
    line: str       # texte brut (zone code)


def find_callers(etude_path: str, paragraphs: List[Paragraph]) -> Dict[str, List[Caller]]:
    """
    Pour chaque paragraphe, trouve les lignes qui font GO TO / PERFORM vers lui.
    Retourne un dict: nom_paragraphe -> liste de Caller.
    """
    if not os.path.exists(etude_path):
        raise FileNotFoundError(f"Fichier introuvable : {etude_path}")

    # Table de lookup : nom_paragraphe -> Paragraph
    para_by_name: Dict[str, Paragraph] = {p.name: p for p in paragraphs}

    callers: Dict[str, List[Caller]] = {p.name: [] for p in paragraphs}

    in_procedure_division = False

    with open(etude_path, "r", encoding="latin-1", errors="ignore") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if len(line) < 72:
                line = line.ljust(72)

            seq = line[0:6]
            code = line[7:72].rstrip()

            if not code:
                continue

            # Detecter PROCEDURE DIVISION
            if code.upper().startswith("PROCEDURE DIVISION"):
                in_procedure_division = True
                continue

            if not in_procedure_division:
                continue

            tokens = code.split()
            if not tokens:
                continue

            # Normaliser en majuscules pour la détection des mots-clés
            upper_tokens = [t.upper() for t in tokens]

            # Recherche GO TO ou PERFORM dans la ligne
            for idx, tok in enumerate(upper_tokens):
                if tok == "GO" and idx + 1 < len(upper_tokens) and upper_tokens[idx + 1] == "TO":
                    # GO TO <nom>
                    if idx + 2 < len(tokens):
                        target_raw = tokens[idx + 2]
                        target_name = target_raw.rstrip(".")
                        if target_name in para_by_name:
                            callers[target_name].append(
                                Caller(seq=seq, call_type="GO TO", line=code)
                            )
                    # on continue la ligne, on pourrait avoir plusieurs appels, mais peu probable
                elif tok == "PERFORM":
                    # PERFORM <nom> ...
                    if idx + 1 < len(tokens):
                        target_raw = tokens[idx + 1]
                        target_name = target_raw.rstrip(".")
                        if target_name in para_by_name:
                            callers[target_name].append(
                                Caller(seq=seq, call_type="PERFORM", line=code)
                            )

    return callers


def print_callers_report(etude_path: str, paragraphs: List[Paragraph], callers: Dict[str, List[Caller]]) -> None:
    prog_name = os.path.basename(etude_path)

    print(f"# Appels GO TO / PERFORM par paragraphe")
    print(f"# Fichier : {prog_name}\n")

    for p in paragraphs:
        name = p.name
        seq = p.seq
        call_list = callers.get(name, [])

        print(f"Paragraphe {name} (seq {seq})")

        if not call_list:
            print("  Appelé par : (aucun)  --> point d'entree possible")
        else:
            print("  Appelé par :")
            for c in call_list:
                print(f"    - {c.seq} via {c.call_type} : {c.line}")

        print()  # ligne vide entre paragraphes


def main():
    if len(sys.argv) != 2:
        print("Usage : python find_callers.py <fichier.cbl.etude>")
        sys.exit(1)

    etude_path = sys.argv[1]

    try:
        paragraphs = extract_paragraphs(etude_path)
        callers = find_callers(etude_path, paragraphs)
        print_callers_report(etude_path, paragraphs, callers)
    except Exception as e:
        print(f"[ERREUR] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
