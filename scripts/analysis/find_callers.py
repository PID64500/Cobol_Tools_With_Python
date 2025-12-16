#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
find_callers.py – version pipeline + version standalone

Contient maintenant :

1) La logique historique (appel en ligne de commande)
2) Une fonction utilisable par main.py :
       find_call_relations(paragraphs_info, config)

Cette fonction retourne :
    {
        "NOMPROGRAMME": {
            "paragraphs": [...],
            "callers": { paragraphe -> liste de Caller }
        },
        ...
    }
"""

import sys
import os
from dataclasses import dataclass
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Modèle
# ─────────────────────────────────────────────────────────────

@dataclass
class Paragraph:
    order: int
    seq: str
    name: str


@dataclass
class Caller:
    seq: str        # séquence de la ligne appelante
    call_type: str  # "GO TO" ou "PERFORM"
    line: str       # texte brut (zone code)


# ─────────────────────────────────────────────────────────────
# Détection paragraphes
# ─────────────────────────────────────────────────────────────

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
    paragraphs: List[Paragraph] = []
    order = 1
    in_procedure_division = False

    if not os.path.exists(etude_path):
        raise FileNotFoundError(f"Fichier introuvable : {etude_path}")

    with open(etude_path, "r", encoding="latin-1", errors="ignore") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if len(line) < 72:
                line = line.ljust(72)

            code = line[7:72].strip()

            # Détection PROCEDURE DIVISION
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


# ─────────────────────────────────────────────────────────────
# Analyse GO TO / PERFORM pour un fichier
# ─────────────────────────────────────────────────────────────

def _analyze_file(etude_path: str) -> Dict[str, Any]:
    """
    Analyse un fichier .cbl.etude :
       - extraction des paragraphes
       - recherche des GO TO / PERFORM

    Retourne :
        {
            "paragraphs": [...],
            "callers": { paragraphe -> liste de Caller }
        }
    """
    logger.debug("Analyse des appels dans %s", etude_path)

    paragraphs = extract_paragraphs(etude_path)
    callers: Dict[str, List[Caller]] = {p.name: [] for p in paragraphs}
    in_procedure_division = False

    # Table de lookup : nom_paragraphe -> Paragraph
    para_by_name = {p.name: p for p in paragraphs}

    with open(etude_path, "r", encoding="latin-1", errors="ignore") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if len(line) < 72:
                line = line.ljust(72)

            seq = line[0:6]
            code = line[7:72].rstrip()

            if not code:
                continue

            # Détection PROCEDURE DIVISION
            if code.upper().startswith("PROCEDURE DIVISION"):
                in_procedure_division = True
                continue

            if not in_procedure_division:
                continue

            tokens = code.split()
            upper_tokens = [t.upper() for t in tokens]

            # Recherche GO TO / PERFORM
            for idx, tok in enumerate(upper_tokens):
                if tok == "GO" and idx + 1 < len(tokens) and upper_tokens[idx + 1] == "TO":
                    # GO TO <nom>
                    if idx + 2 < len(tokens):
                        target = tokens[idx + 2].rstrip(".")
                        if target in para_by_name:
                            callers[target].append(
                                Caller(seq=seq, call_type="GO TO", line=code)
                            )

                elif tok == "PERFORM":
                    if idx + 1 < len(tokens):
                        target = tokens[idx + 1].rstrip(".")
                        if target in para_by_name:
                            callers[target].append(
                                Caller(seq=seq, call_type="PERFORM", line=code)
                            )

    return {
        "paragraphs": paragraphs,
        "callers": callers,
    }


# ─────────────────────────────────────────────────────────────
# Fonction utilisée par main.py (pipeline)
# ─────────────────────────────────────────────────────────────

def find_call_relations(paragraphs_info: Dict[str, Any], config: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """
    Fonction attendue par main.py dans le pipeline.

    paragraphs_info = dict :
        clé = chemin du fichier .cbl.etude
        valeur = liste de Paragraph (ancienne structure)

    Retourne un dict :
        {
            "PROGRAMME": {
                "paragraphs": [...],
                "callers": {paragraphe -> liste Caller}
            }
        }
    """

    logger.info("find_call_relations : début analyse GO TO / PERFORM")

    results: Dict[str, Any] = {}

    for etude_path in paragraphs_info.keys():
        try:
            analysis = _analyze_file(etude_path)

            # Nom programme = nom fichier sans extension
            filename = os.path.basename(etude_path)
            program_name = filename.split(".")[0]

            results[program_name] = analysis

        except Exception as e:
            logger.error("Erreur analyse GO TO/PERFORM dans %s : %s", etude_path, e)

    logger.info("find_call_relations : analyse terminée (%d programmes)", len(results))
    return results


# ─────────────────────────────────────────────────────────────
# Version standalone (appel direct)
# ─────────────────────────────────────────────────────────────

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

        print()


def main():
    if len(sys.argv) != 2:
        print("Usage : python find_callers.py <fichier.cbl.etude>")
        sys.exit(1)

    etude_path = sys.argv[1]

    try:
        paragraphs = extract_paragraphs(etude_path)
        callers = _analyze_file(etude_path)["callers"]
        print_callers_report(etude_path, paragraphs, callers)
    except Exception as e:
        print(f"[ERREUR] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
