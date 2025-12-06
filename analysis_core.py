#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
analysis_core.py
----------------
Fonctions communes d'analyse pour un programme COBOL normalisé (.cbl.etude).

Objectif :
    - Extraire les paragraphes
    - Identifier les appels internes (GO TO / PERFORM / PERFORM THRU)
    - Identifier les points de sortie (EXEC CICS XCTL / RETURN / GOBACK / STOP RUN)
    - Fournir une structure de données unique exploitable par les scripts de rapport.

Usage typique :
    from analysis_core import analyze_program

    result = analyze_program(".../MONPROG.cbl.etude")
"""

from dataclasses import dataclass
from typing import List, Dict, Tuple
import os
import re


# ===========================
#   Modèles de données
# ===========================

@dataclass
class Paragraph:
    order: int
    seq: str
    name: str
    start_index: int  # indice (0-based) de la ligne dans le fichier


@dataclass
class Caller:
    src_paragraph: str
    seq: str           # séquence de la ligne d'appel
    kind: str          # GO TO / PERFORM / PERFORM THRU
    line_text: str     # ligne COBOL brute (colonnes 7-72)


@dataclass
class ExitEvent:
    paragraph: str
    seq: str
    kind: str          # XCTL / RETURN / GOBACK / STOP RUN
    label: str         # ex : "XCTL PROGRAM", "RETURN SRAB"
    line_text: str     # ligne COBOL brute (colonnes 7-72)


@dataclass
class AnalysisResult:
    program_name: str
    etude_path: str
    paragraphs: List[Paragraph]
    callers_by_target: Dict[str, List[Caller]]
    exits_by_paragraph: Dict[str, List[ExitEvent]]
    entry_points: List[str]
    stats: Dict[str, int]


# ===========================
#   Fonctions internes
# ===========================

def _read_etude_lines(etude_path: str) -> List[str]:
    """
    Lit le fichier .cbl.etude et normalise les lignes à 72 colonnes (1-6 = seq, 7-72 = code).
    """
    with open(etude_path, "r", encoding="latin-1", errors="ignore") as f:
        raw_lines = [ln.rstrip("\n") for ln in f]

    lines: List[str] = []
    for ln in raw_lines:
        if len(ln) < 72:
            ln = ln.ljust(72)
        else:
            ln = ln[:72]
        lines.append(ln)
    return lines


def _is_paragraph_line(line: str) -> bool:
    """
    Détermine si une ligne de .cbl.etude contient un début de paragraphe COBOL.

    Format .etude supposé :
      - colonnes 1-6  : numéro de séquence
      - colonne 7     : généralement espace (pas de commentaires ici)
      - colonnes 8-72 : code COBOL

    Critère :
      - col 8 (index 7) non blanche
      - premier token du code se termine par '.'
    """
    if len(line) < 8:
        return False

    # Colonne 7 (index 6) : si '*' ce serait un commentaire dans le COBOL d'origine,
    # mais normalement on a déjà filtré tout ça dans la normalisation.
    if line[7] == " ":
        return False

    code = line[7:72].strip()
    if not code:
        return False

    first_token = code.split()[0]
    return first_token.endswith(".")


def _extract_paragraphs(lines: List[str]) -> List[Paragraph]:
    """
    Extrait la liste des paragraphes avec leurs positions.
    On commence après 'PROCEDURE DIVISION'.
    """
    paragraphs: List[Paragraph] = []
    in_procedure_division = False
    order = 1

    for idx, line in enumerate(lines):
        code = line[7:72].strip()

        if code.upper().startswith("PROCEDURE DIVISION"):
            in_procedure_division = True
            continue

        if not in_procedure_division:
            continue

        if _is_paragraph_line(line):
            seq = line[0:6]
            first_token = code.split()[0]
            name = first_token.rstrip(".")
            paragraphs.append(Paragraph(order=order, seq=seq, name=name, start_index=idx))
            order += 1

    return paragraphs


# Regex pour PROGRAM('XXX') et TRANSID('XXX')
RE_PROGRAM = re.compile(r"PROGRAM\(['\"]([^'\"]+)['\"]\)", re.IGNORECASE)
RE_TRANSID = re.compile(r"TRANSID\(['\"]([^'\"]+)['\"]\)", re.IGNORECASE)


def _normalize_target_name(raw: str, para_names: set) -> str:
    """
    Normalise un nom de cible (GO TO / PERFORM) pour essayer
    de le faire correspondre à un paragraphe existant.

    - supprime le '.' final
    - si termine par '-F', essaye sans le '-F'

    Retourne "" si aucune correspondance.
    """
    base = raw.rstrip(".")
    if base in para_names:
        return base

    if base.endswith("-F"):
        cand = base[:-2]
        if cand in para_names:
            return cand

    return ""


def _scan_calls_and_exits(lines: List[str],
                          paragraphs: List[Paragraph]
                          ) -> Tuple[Dict[str, List[Caller]], Dict[str, List[ExitEvent]], Dict[str, int]]:
    """
    Balaye les paragraphes pour :
      - construire la liste des appels internes (GO TO / PERFORM / PERFORM THRU)
      - construire la liste des sorties par paragraphe
      - calculer quelques stats

    Retourne :
      callers_by_target : { nom_paragraphe : [Caller, ...] }
      exits_by_paragraph : { nom_paragraphe : [ExitEvent, ...] }
      stats : {
          nb_paragraphs,
          nb_calls_total,
          nb_goto,
          nb_perform,
          nb_perform_thru,
          nb_exit_events
      }
    """
    para_names = {p.name for p in paragraphs}
    callers_by_target: Dict[str, List[Caller]] = {p.name: [] for p in paragraphs}
    exits_by_paragraph: Dict[str, List[ExitEvent]] = {p.name: [] for p in paragraphs}

    nb_goto = 0
    nb_perform = 0
    nb_perform_thru = 0
    nb_exit_events = 0

    for idx_p, p in enumerate(paragraphs):
        start = p.start_index + 1
        end = paragraphs[idx_p + 1].start_index if idx_p + 1 < len(paragraphs) else len(lines)

        for i in range(start, end):
            line = lines[i]
            seq = line[0:6]
            code = line[7:72].rstrip()
            if not code:
                continue

            upper = code.upper()
            tokens = code.replace(".", " ").split()
            upper_tokens = upper.replace(".", " ").split()

            # ----------------
            # Détection GO TO
            # ----------------
            if "GO" in upper_tokens and "TO" in upper_tokens:
                try:
                    idx_to = upper_tokens.index("TO")
                    raw_target = tokens[idx_to + 1]
                    target = _normalize_target_name(raw_target, para_names)
                    if target:
                        nb_goto += 1
                        callers_by_target[target].append(
                            Caller(
                                src_paragraph=p.name,
                                seq=seq,
                                kind="GO TO",
                                line_text=code
                            )
                        )
                except Exception:
                    pass

            # ----------------
            # Détection PERFORM
            # ----------------
            if "PERFORM" in upper_tokens:
                try:
                    idx_p = upper_tokens.index("PERFORM")
                    raw_target = tokens[idx_p + 1]
                    target = _normalize_target_name(raw_target, para_names)

                    # Ignorer les PERFORM SMAD-xxxx (traces)
                    if target and not target.upper().startswith("SMAD-"):
                        nb_perform += 1
                        callers_by_target[target].append(
                            Caller(
                                src_paragraph=p.name,
                                seq=seq,
                                kind="PERFORM",
                                line_text=code
                            )
                        )

                    # Cas PERFORM X THRU Y
                    if "THRU" in upper_tokens:
                        try:
                            idx_t = upper_tokens.index("THRU")
                            raw_target2 = tokens[idx_t + 1]
                            target2 = _normalize_target_name(raw_target2, para_names)
                            if target2 and not target2.upper().startswith("SMAD-"):
                                nb_perform_thru += 1
                                callers_by_target[target2].append(
                                    Caller(
                                        src_paragraph=p.name,
                                        seq=seq,
                                        kind="PERFORM THRU",
                                        line_text=code
                                    )
                                )
                        except Exception:
                            pass

                except Exception:
                    pass

            # ----------------
            # Détection sorties (XCTL / RETURN / GOBACK / STOP RUN)
            # ----------------
            up = upper
            toks = upper.split()

            # EXEC CICS XCTL
            if "EXEC CICS" in up and "XCTL" in up:
                m = RE_PROGRAM.search(code)
                if m:
                    prog = m.group(1)
                    label = f"XCTL {prog}"
                else:
                    label = "XCTL"
                nb_exit_events += 1
                exits_by_paragraph[p.name].append(
                    ExitEvent(
                        paragraph=p.name,
                        seq=seq,
                        kind="XCTL",
                        label=label,
                        line_text=code
                    )
                )

            # EXEC CICS RETURN
            if "EXEC CICS" in up and "RETURN" in up:
                m_t = RE_TRANSID.search(code)
                if m_t:
                    trans = m_t.group(1)
                    label = f"RETURN {trans}"
                else:
                    label = "RETURN"
                nb_exit_events += 1
                exits_by_paragraph[p.name].append(
                    ExitEvent(
                        paragraph=p.name,
                        seq=seq,
                        kind="RETURN",
                        label=label,
                        line_text=code
                    )
                )

            # GOBACK
            if "GOBACK" in toks:
                nb_exit_events += 1
                exits_by_paragraph[p.name].append(
                    ExitEvent(
                        paragraph=p.name,
                        seq=seq,
                        kind="GOBACK",
                        label="GOBACK",
                        line_text=code
                    )
                )

            # STOP RUN
            if "STOP" in toks and "RUN" in toks:
                nb_exit_events += 1
                exits_by_paragraph[p.name].append(
                    ExitEvent(
                        paragraph=p.name,
                        seq=seq,
                        kind="STOP RUN",
                        label="STOP RUN",
                        line_text=code
                    )
                )

    stats = {
        "nb_paragraphs": len(paragraphs),
        "nb_calls_total": nb_goto + nb_perform + nb_perform_thru,
        "nb_goto": nb_goto,
        "nb_perform": nb_perform,
        "nb_perform_thru": nb_perform_thru,
        "nb_exit_events": nb_exit_events,
    }

    return callers_by_target, exits_by_paragraph, stats


# ===========================
#   API principale
# ===========================

def analyze_program(etude_path: str) -> AnalysisResult:
    """
    Analyse un fichier .cbl.etude et renvoie un AnalysisResult.

    etude_path : chemin complet vers le fichier .cbl.etude
    """
    if not os.path.exists(etude_path):
        raise FileNotFoundError(f"Fichier introuvable : {etude_path}")

    lines = _read_etude_lines(etude_path)
    paragraphs = _extract_paragraphs(lines)
    callers_by_target, exits_by_paragraph, stats = _scan_calls_and_exits(lines, paragraphs)

    # Points d'entrée : paragraphes sans aucun caller
    entry_points = [
        p.name
        for p in paragraphs
        if not callers_by_target.get(p.name)
    ]

    program_name = os.path.basename(etude_path).replace(".cbl.etude", "")

    return AnalysisResult(
        program_name=program_name,
        etude_path=os.path.abspath(etude_path),
        paragraphs=paragraphs,
        callers_by_target=callers_by_target,
        exits_by_paragraph=exits_by_paragraph,
        entry_points=entry_points,
        stats=stats,
    )


if __name__ == "__main__":
    # Petit test manuel éventuel :
    import sys
    if len(sys.argv) != 2:
        print("Usage : python analysis_core.py chemin/MONPROG.cbl.etude")
        sys.exit(1)

    res = analyze_program(sys.argv[1])
    print(f"Programme : {res.program_name}")
    print(f"Paragraphes : {res.stats['nb_paragraphs']}")
    print(f"Appels internes : {res.stats['nb_calls_total']}")
    print(f"Sorties : {res.stats['nb_exit_events']}")
    print("Points d'entrée potentiels :")
    for ep in res.entry_points:
        print(f"  - {ep}")
