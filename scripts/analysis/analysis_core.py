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
    - Analyser les variables déclarées (WORKING/LOCAL/LINKAGE) et détecter les variables jamais utilisées
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
class VariableInfo:
    """
    Informations sur une variable COBOL (DATA DIVISION).
    """
    name: str              # nom de variable (en majuscules)
    section: str           # WORKING-STORAGE / LINKAGE / LOCAL-STORAGE
    level: str             # niveau (01, 05, 77, ...)
    seq: str               # numéro de séquence de la ligne de déclaration
    decl_line: str         # ligne de déclaration (colonnes 7-72)
    usage_count: int = 0   # nombre d'occurrences dans PROCEDURE DIVISION


@dataclass
class AnalysisResult:
    program_name: str
    etude_path: str
    paragraphs: List[Paragraph]
    callers_by_target: Dict[str, List[Caller]]
    exits_by_paragraph: Dict[str, List[ExitEvent]]
    entry_points: List[str]
    stats: Dict[str, int]
    variables: List[VariableInfo]
    unused_variables: List[VariableInfo]


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


def _scan_calls_and_exits(
    lines: List[str],
    paragraphs: List[Paragraph]
) -> Tuple[Dict[str, List[Caller]], Dict[str, List[ExitEvent]], Dict[str, int]]:
    """
    Balaye les paragraphes pour :
      - construire la liste des appels internes (GO TO / PERFORM / PERFORM THRU)
      - construire la liste des sorties par paragraphe
      - calculer quelques stats
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
                    idx_perf = upper_tokens.index("PERFORM")
                    raw_target = tokens[idx_perf + 1]
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
#   Analyse des variables
# ===========================

def _extract_variables(lines: List[str]) -> List[VariableInfo]:
    """
    Parcourt les sections WORKING-STORAGE / LOCAL-STORAGE / LINKAGE
    pour extraire les variables déclarées.

    On ne dépend PAS de la présence explicite de "DATA DIVISION",
    ce qui colle mieux à ton .etude.
    """
    variables: List[VariableInfo] = []

    current_section: str = ""
    for line in lines:
        code_raw = line[7:72]
        code = code_raw.strip()
        upper = code.upper()

        # Fin des données : début PROCEDURE DIVISION
        if "PROCEDURE DIVISION" in upper:
            break

        # Détection de section
        if "WORKING-STORAGE SECTION" in upper:
            current_section = "WORKING-STORAGE"
            continue
        if "LOCAL-STORAGE SECTION" in upper:
            current_section = "LOCAL-STORAGE"
            continue
        if "LINKAGE SECTION" in upper:
            current_section = "LINKAGE"
            continue

        if not current_section:
            # on n'est pas dans une section de stockage
            continue

        if not code:
            continue

        tokens = code.split()
        if not tokens:
            continue

        level = tokens[0]
        if not level[0].isdigit():
            # pas un niveau → pas une déclaration
            continue

        # on ignore 66 / 88 (RENAMES / condition names)
        if level in ("66", "88"):
            continue

        if len(tokens) < 2:
            continue

        raw_name = tokens[1].rstrip(".,")
        if raw_name.upper() == "FILLER":
            # FILLER → pas une variable nommée
            continue

        var_name = raw_name.upper()
        seq = line[0:6]
        decl_line = code_raw.rstrip()

        variables.append(
            VariableInfo(
                name=var_name,
                section=current_section,
                level=level,
                seq=seq,
                decl_line=decl_line,
                usage_count=0,
            )
        )

    return variables


def _compute_variable_usage(lines: List[str], variables: List[VariableInfo]) -> None:
    """
    Compte le nombre d'occurrences de chaque variable dans la PROCEDURE DIVISION.
    """
    if not variables:
        return

    # Localiser PROCEDURE DIVISION
    proc_start = None
    for idx, line in enumerate(lines):
        code = line[7:72].upper()
        if code.startswith("PROCEDURE DIVISION"):
            proc_start = idx
            break

    if proc_start is None:
        return

    # Préparer les regex pour chaque variable
    var_patterns: List[Tuple[VariableInfo, re.Pattern]] = []
    for v in variables:
        name = v.name.upper()
        # Nom complet : éviter de matcher W-CNT dans W-CNT-TOTAL
        pattern = re.compile(rf"(?<![A-Z0-9-]){re.escape(name)}(?![A-Z0-9-])")
        v.usage_count = 0
        var_patterns.append((v, pattern))

    # Balayer la PROCEDURE DIVISION
    for line in lines[proc_start + 1:]:
        code_upper = line[7:72].upper()
        if not code_upper.strip():
            continue

        for v, pat in var_patterns:
            matches = pat.findall(code_upper)
            if matches:
                v.usage_count += len(matches)


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

    # --- Analyse des variables ---
    variables = _extract_variables(lines)
    _compute_variable_usage(lines, variables)
    unused_variables = [v for v in variables if v.usage_count == 0]

    stats["nb_variables_declared"] = len(variables)
    stats["nb_variables_used"] = len(variables) - len(unused_variables)
    stats["nb_variables_unused"] = len(unused_variables)

    # Points d'entrée : paragraphes "vrais" (nom commençant par un chiffre)
    # et sans aucun caller. On filtre les END-EXEC., END-IF., EXIT., etc.
    entry_points = [
        p.name
        for p in paragraphs
        if p.name and p.name[0].isdigit() and not callers_by_target.get(p.name)
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
        variables=variables,
        unused_variables=unused_variables,
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
    print(f"Variables déclarées : {res.stats.get('nb_variables_declared', 0)}")
    print(f"Variables utilisées : {res.stats.get('nb_variables_used', 0)}")
    print(f"Variables inutilisées : {res.stats.get('nb_variables_unused', 0)}")
    print("Points d'entrée potentiels :")
    for ep in res.entry_points:
        print(f"  - {ep}")
