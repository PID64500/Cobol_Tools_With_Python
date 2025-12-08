#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
report_markdown.py
------------------
Génère un rapport Markdown pour un programme COBOL (.cbl.etude)
en s'appuyant sur analysis_core.py via analysis_core_wrapper.
"""

import os
import sys
from typing import Dict, List, Set, Tuple

import yaml
import logging

logger = logging.getLogger(__name__)

from analysis_core_wrapper import (
    analyze_program,
    Paragraph,
    Caller,
    ExitEvent,
    AnalysisResult,
)


# ============================================================
#   Utilitaires de config et de classification
# ============================================================

def load_config(config_path: str = "config.yaml") -> Dict:
    if not os.path.exists(config_path):
        return {"output_dir": "./output"}
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def classify_paragraph(name: str) -> str:
    u = name.upper()
    if name.startswith("000-") or "INIT" in u:
        return "Initialisation"
    if "PF" in u:
        return "Gestion PFKEY / commande"
    if u.startswith("SRHP-"):
        return "Bloc commun SRHP"
    if "ANO" in u or "ANOM" in u or "ZZ" in u:
        return "Gestion d'anomalies"
    return "Traitement"


# ============================================================
#   Construction du graphe d'appels
# ============================================================

def build_call_graph(analysis: AnalysisResult) -> Dict[str, Set[str]]:
    """
    Graphe des appels internes (GO TO / PERFORM) :
      call_graph[source] = { target1, target2, ... }
    """
    call_graph: Dict[str, Set[str]] = {p.name: set() for p in analysis.paragraphs}

    for target, callers in analysis.callers_by_target.items():
        for c in callers:
            call_graph.setdefault(c.src_paragraph, set()).add(target)

    return call_graph


# ============================================================
#   Analyses structurelles avancées sur le graphe
# ============================================================

def compute_degrees(
    analysis: AnalysisResult,
    call_graph: Dict[str, Set[str]],
) -> Dict[str, Dict[str, int]]:
    """
    Calcule pour chaque paragraphe :
      - in_deg  : nb d'appels entrants
      - out_deg : nb d'appels sortants internes
    """
    degrees: Dict[str, Dict[str, int]] = {}

    for p in analysis.paragraphs:
        name = p.name
        in_deg = len(analysis.callers_by_target.get(name, []))
        out_deg = len(call_graph.get(name, []))
        degrees[name] = {"in": in_deg, "out": out_deg}

    return degrees


def compute_longest_paths(
    entry_points: List[str],
    call_graph: Dict[str, Set[str]],
) -> Tuple[int, List[List[str]]]:
    """
    Calcule la longueur maximale des chaînes d'appel (en nb de nœuds)
    et quelques exemples de chemins correspondants.

    On fait un DFS depuis chaque entry point, en évitant les boucles infinies
    via un 'stack' local (chemin courant).
    """
    max_len = 0
    examples: List[List[str]] = []

    def dfs(current: str, stack: List[str]):
        nonlocal max_len, examples
        if current in stack:
            # cycle détecté, on arrête ce chemin
            return
        stack.append(current)
        succ = sorted(call_graph.get(current, []))
        if not succ:
            # fin de chaîne
            l = len(stack)
            if l > max_len:
                max_len = l
                examples = [stack.copy()]
            elif l == max_len and l > 0:
                if len(examples) < 5:
                    examples.append(stack.copy())
        else:
            for s in succ:
                dfs(s, stack)
        stack.pop()

    for ep in entry_points:
        dfs(ep, [])

    return max_len, examples


def find_cycles(call_graph: Dict[str, Set[str]]) -> List[List[str]]:
    """
    Détecte quelques cycles simples dans le graphe d'appels.
    On ne cherche pas l'exhaustivité parfaite, mais de quoi signaler
    dans l'analyse des risques qu'il existe des boucles dans les appels.
    """
    cycles: List[List[str]] = []
    visited: Set[str] = set()
    stack: List[str] = []

    def dfs(node: str):
        if node in stack:
            idx = stack.index(node)
            cycle = stack[idx:] + [node]
            if cycle not in cycles and len(cycles) < 5:
                cycles.append(cycle)
            return
        if node in visited:
            return
        visited.add(node)
        stack.append(node)
        for nxt in call_graph.get(node, []):
            dfs(nxt)
        stack.pop()

    for n in call_graph.keys():
        if n not in visited:
            dfs(n)

    return cycles


def compute_reachable_from_entry_points(
    entry_points: List[str],
    call_graph: Dict[str, Set[str]],
) -> Set[str]:
    """
    Ensemble des paragraphes atteignables depuis au moins un point d'entrée.
    """
    reachable: Set[str] = set()

    def dfs(node: str):
        if node in reachable:
            return
        reachable.add(node)
        for nxt in call_graph.get(node, []):
            dfs(nxt)

    for ep in entry_points:
        dfs(ep)

    return reachable


# ============================================================
#   Score de propreté du code
# ============================================================

def compute_cleanliness_score(
    analysis: AnalysisResult,
    call_graph: Dict[str, Set[str]],
) -> Dict[str, object]:
    """
    Calcule un "score de propreté" global (0-100) basé sur :
      - nb de GO TO
      - ratio de variables inutilisées
      - présence de cycles dans le graphe
      - profondeur maximale des chaînes d'appel
      - nb de paragraphes inaccessibles
    """
    s = analysis.stats
    nb_goto = s.get("nb_goto", 0)
    nb_decl = s.get("nb_variables_declared", 0)
    nb_unused = s.get("nb_variables_unused", 0)
    nb_paras = s.get("nb_paragraphs", 0)

    # 1. Pénalité liée aux GO TO
    penalty_goto = min(30, nb_goto * 2)

    # 2. Variables mortes
    ratio_dead = 0.0
    if nb_decl > 0:
        ratio_dead = nb_unused / nb_decl * 100.0
    # Jusqu'à 25 points de pénalité si beaucoup de variables mortes
    penalty_deadvars = min(25, int(ratio_dead * 0.3))

    # 3. Cycles
    cycles = find_cycles(call_graph)
    penalty_cycles = 15 if cycles else 0

    # 4. Profondeur des chaînes d'appel
    penalty_depth = 0
    if analysis.entry_points:
        max_len, _ = compute_longest_paths(analysis.entry_points, call_graph)
        if max_len >= 8:
            penalty_depth = 10
        elif max_len >= 6:
            penalty_depth = 5

    # 5. Paragraphes inaccessibles
    penalty_unreachable = 0
    nb_unreachable = 0
    if analysis.entry_points and nb_paras > 0:
        reachable = compute_reachable_from_entry_points(analysis.entry_points, call_graph)
        unreachable = [
            p.name for p in analysis.paragraphs
            if p.name not in reachable
        ]
        nb_unreachable = len(unreachable)
        penalty_unreachable = min(15, nb_unreachable * 2)

    total_penalty = penalty_goto + penalty_deadvars + penalty_cycles + penalty_depth + penalty_unreachable
    score = max(0, 100 - total_penalty)

    # Libellé qualitatif
    if score >= 80:
        label = "Très bon"
    elif score >= 60:
        label = "Correct"
    elif score >= 40:
        label = "À surveiller"
    else:
        label = "Critique"

    breakdown = {
        "score": score,
        "label": label,
        "ratio_dead": ratio_dead,
        "penalty_goto": penalty_goto,
        "penalty_deadvars": penalty_deadvars,
        "penalty_cycles": penalty_cycles,
        "penalty_depth": penalty_depth,
        "penalty_unreachable": penalty_unreachable,
        "nb_unreachable": nb_unreachable,
        "has_cycles": bool(cycles),
    }

    # On stocke le score dans les stats pour d'autres rapports éventuels
    analysis.stats["cleanliness_score"] = score
    analysis.stats["cleanliness_label"] = label

    return breakdown


# ============================================================
#   Sections du rapport
# ============================================================

def write_table_of_contents(f):
    f.write("## Sommaire\n\n")
    f.write("- [Synthèse générale](#synthèse-générale)\n")
    f.write("- [Vue synthétique des flux](#vue-synthétique-des-flux)\n")
    f.write("- [Table des paragraphes](#table-des-paragraphes)\n")
    f.write("- [Analyse des risques](#analyse-des-risques)\n")
    f.write("- [Variables inutilisées et score de propreté](#variables-inutilisées-et-score-de-propreté)\n")
    f.write("- [Détail par paragraphe](#détail-par-paragraphe)\n\n")


def write_flow_overview(f, analysis: AnalysisResult, call_graph: Dict[str, Set[str]]):
    f.write("## Vue synthétique des flux\n\n")

    if not analysis.entry_points:
        f.write(
            "Aucun flux logique évident à partir des paragraphes analysés. "
            "L'enchaînement réel dépendra du contexte d'appel (JCL, transaction CICS, etc.).\n\n"
        )
        return

    for ep in analysis.entry_points:
        visited: Set[str] = set()
        queue: List[str] = [ep]
        lines: List[str] = []
        has_flow = False

        while queue:
            src = queue.pop(0)
            if src in visited:
                continue
            visited.add(src)

            succ = sorted(call_graph.get(src, []))
            if not succ:
                continue

            has_flow = True
            succ_list = ", ".join(f"`{t}`" for t in succ)
            lines.append(f"- `{src}` → {succ_list}\n")

            for t in succ:
                if t not in visited:
                    queue.append(t)

        if has_flow:
            f.write(f"### Flux à partir de `{ep}`\n\n")
            for line in lines:
                f.write(line)
            f.write("\n")


def write_risk_analysis(f, analysis: AnalysisResult, call_graph: Dict[str, Set[str]]):
    """
    Analyse structurelle enrichie :
      - nb de GO TO
      - paragraphes avec plusieurs sorties
      - paragraphes très sollicités (entrants)
      - paragraphes "hub" (beaucoup d'entrants ET de sortants)
      - paragraphes isolés
      - paragraphes inaccessibles depuis les points d'entrée
      - gestion d'anomalies centralisée
      - profondeur maximale des chaînes d'appel
      - cycles dans le graphe
    """
    f.write("## Analyse des risques\n\n")

    s = analysis.stats
    risks: List[str] = []

    degrees = compute_degrees(analysis, call_graph)

    # 1. Présence de GO TO
    if s.get("nb_goto", 0) > 0:
        risks.append(
            f"⚠ Le programme contient **{s['nb_goto']}** instructions `GO TO` "
            "→ complexité de lecture accrue."
        )

    # 2. Paragraphes avec plusieurs sorties
    multi_exit_paras = [
        p.name for p in analysis.paragraphs
        if len(analysis.exits_by_paragraph.get(p.name, [])) > 1
    ]
    if multi_exit_paras:
        risk = (
            "⚠ Paragraphes avec plusieurs points de sortie "
            "(XCTL / RETURN / GOBACK / STOP RUN) :\n\n"
        )
        for n in multi_exit_paras:
            risk += f"- `{n}`\n"
        risk += "\n"
        risks.append(risk)

    # 3. Paragraphes très sollicités (beaucoup d'entrants)
    high_in_degree = [
        name for name, deg in degrees.items()
        if deg["in"] >= 3
    ]
    if high_in_degree:
        risk = "⚠ Paragraphes très sollicités (≥ 3 appels entrants) :\n\n"
        for n in high_in_degree:
            risk += f"- `{n}`\n"
        risk += "\n"
        risks.append(risk)

    # 4. Paragraphes "hub" : beaucoup d'entrants ET de sortants
    hubs = [
        name for name, deg in degrees.items()
        if deg["in"] >= 3 and deg["out"] >= 3
    ]
    if hubs:
        risk = (
            "⚠ Paragraphes jouant un rôle de 'hub' "
            "(beaucoup d'entrants et de sortants) :\n\n"
        )
        for n in hubs:
            risk += f"- `{n}`\n"
        risk += "\n"
        risks.append(risk)

    # 5. Paragraphes isolés (aucun entrant, aucune sortie interne, aucune sortie CICS)
    isolated = []
    for p in analysis.paragraphs:
        callers = analysis.callers_by_target.get(p.name, [])
        exits = analysis.exits_by_paragraph.get(p.name, [])
        out_deg = degrees[p.name]["out"]
        if not callers and not exits and out_deg == 0:
            isolated.append(p.name)
    if isolated:
        risk = (
            "ℹ Paragraphes isolés (non appelés et sans sortie) : "
            "potentiellement du code mort ou des reliquats d'évolutions :\n\n"
        )
        for n in isolated:
            risk += f"- `{n}`\n"
        risk += "\n"
        risks.append(risk)

    # 6. Paragraphes inaccessibles depuis les points d'entrée
    unreachable: List[str] = []
    if analysis.entry_points:
        reachable = compute_reachable_from_entry_points(analysis.entry_points, call_graph)
        unreachable = [
            p.name
            for p in analysis.paragraphs
            if p.name not in reachable
        ]
        if unreachable:
            risk = (
                "⚠ Paragraphes inaccessibles depuis les points d'entrée "
                "(non atteints par les enchaînements GOTO/PERFORM) :\n\n"
            )
            for n in unreachable:
                risk += f"- `{n}`\n"
            risk += "\n"
            risks.append(risk)

    # 7. Gestion d'anomalies centralisée
    anomaly_paras = [
        p.name for p in analysis.paragraphs
        if "ANO" in p.name.upper() or "ANOM" in p.name.upper() or "ZZ" in p.name.upper()
    ]
    hotspot_anom = [
        n for n in anomaly_paras
        if len(analysis.callers_by_target.get(n, [])) >= 2
    ]
    if hotspot_anom:
        risk = (
            "ℹ Gestion d'anomalies centralisée dans les paragraphes suivants "
            "(points critiques du flux) :\n\n"
        )
        for n in hotspot_anom:
            risk += f"- `{n}`\n"
        risk += "\n"
        risks.append(risk)

    # 8. Profondeur maximale des chaînes d'appel
    if analysis.entry_points:
        max_len, examples = compute_longest_paths(analysis.entry_points, call_graph)
        if max_len > 0:
            if max_len >= 6:
                prefix = "⚠ Chaînes d'appel longues"
            else:
                prefix = "ℹ Chaînes d'appel"

            if examples:
                ex_path = " → ".join(f"`{n}`" for n in examples[0])
                risks.append(
                    f"{prefix} : profondeur maximale **{max_len}** paragraphe(s) "
                    f"depuis un point d'entrée. Exemple : {ex_path}.\n"
                )
            else:
                risks.append(
                    f"{prefix} : profondeur maximale **{max_len}** paragraphe(s) "
                    "depuis un point d'entrée.\n"
                )

    # 9. Cycles dans le graphe
    cycles = find_cycles(call_graph)
    if cycles:
        risk = "⚠ Cycles détectés dans les appels de paragraphes (boucles logiques possibles) :\n\n"
        for cyc in cycles:
            risk += "- " + " → ".join(f"`{n}`" for n in cyc) + "\n"
        risk += "\n"
        risks.append(risk)

    # Bilan
    if not risks:
        f.write(
            "Aucun risque structurel majeur détecté à partir de la seule analyse "
            "des paragraphes, appels internes et sorties. Des vérifications "
            "complémentaires (tests, logs CICS, JCL) restent nécessaires.\n\n"
        )
    else:
        for r in risks:
            f.write(f"{r}\n")


def write_variables_and_cleanliness(
    f,
    analysis: AnalysisResult,
    call_graph: Dict[str, Set[str]],
):
    """
    Section dédiée :
      - récap variables déclarées / inutilisées
      - taux de variables mortes
      - score de propreté global
      - tableau "Variables inutilisées" par section
    """
    s = analysis.stats
    total_decl = s.get("nb_variables_declared", 0)
    total_unused = s.get("nb_variables_unused", 0)
    total_used = s.get("nb_variables_used", 0)

    if total_decl > 0:
        taux_mortes = (total_unused / total_decl) * 100.0
    else:
        taux_mortes = 0.0

    # Score de propreté global
    cleanliness = compute_cleanliness_score(analysis, call_graph)

    f.write("## Variables inutilisées et score de propreté\n\n")

    f.write("### Synthèse variables\n\n")
    f.write(f"- Variables déclarées : **{total_decl}**\n")
    f.write(f"- Variables utilisées au moins une fois : **{total_used}**\n")
    f.write(f"- Variables inutilisées : **{total_unused}**\n")
    f.write(f"- Taux de variables mortes : **{taux_mortes:.1f} %**\n\n")

    f.write("### Score de propreté du code\n\n")
    f.write(
        f"- Score global de propreté : **{cleanliness['score']}/100** "
        f"({cleanliness['label']})\n"
    )
    f.write(
        "- Facteurs pris en compte : GO TO, variables mortes, cycles d'appels, "
        "profondeur des chaînes d'appel, paragraphes inaccessibles.\n\n"
    )

    f.write("Détail des principales pénalités appliquées :\n\n")
    f.write(
        f"- Pénalité liée aux GO TO : **-{cleanliness['penalty_goto']}**\n"
        f"- Pénalité liée aux variables mortes : **-{cleanliness['penalty_deadvars']}** "
        f"(taux ≈ {cleanliness['ratio_dead']:.1f} %)\n"
        f"- Pénalité liée aux cycles : **-{cleanliness['penalty_cycles']}**\n"
        f"- Pénalité liée à la profondeur des chaînes : **-{cleanliness['penalty_depth']}**\n"
        f"- Pénalité liée aux paragraphes inaccessibles : "
        f"**-{cleanliness['penalty_unreachable']}** "
        f"(parag. inaccessibles : {cleanliness['nb_unreachable']})\n\n"
    )

    # Tableau des variables inutilisées par section
    f.write("### Tableau des variables inutilisées par section\n\n")

    if total_decl == 0:
        f.write("Aucune variable déclarée dans la DATA DIVISION.\n\n")
        return

    if not getattr(analysis, "unused_variables", None):
        f.write(
            "Aucune variable déclarée n'apparaît comme totalement inutilisée "
            "dans la PROCEDURE DIVISION.\n\n"
        )
        return

    # Regroupement par section (WORKING-STORAGE, LINKAGE, LOCAL-STORAGE, ...)
    by_section: Dict[str, List] = {}
    for v in analysis.unused_variables:
        by_section.setdefault(v.section, []).append(v)

    for section, vars_sec in sorted(by_section.items()):
        f.write(f"#### Section {section}\n\n")
        f.write("| Niveau | Nom | Seq | Déclaration |\n")
        f.write("|--------|-----|-----|-------------|\n")
        for v in sorted(vars_sec, key=lambda x: (x.level, x.name)):
            decl_preview = v.decl_line.strip()
            if len(decl_preview) > 80:
                decl_preview = decl_preview[:77] + "."
            f.write(
                f"| {v.level} | `{v.name}` | {v.seq.strip()} | `{decl_preview}` |\n"
            )
        f.write("\n")


# ============================================================
#   Rapport Markdown
# ============================================================

def make_markdown_report(etude_path: str, output_dir: str) -> str:
    analysis = analyze_program(etude_path)
    call_graph = build_call_graph(analysis)

    prog_name = analysis.program_name
    md_name = f"{prog_name}_report.md"
    os.makedirs(output_dir, exist_ok=True)
    md_path = os.path.join(output_dir, md_name)

    with open(md_path, "w", encoding="utf-8") as f:

        f.write(f"# Rapport d'analyse COBOL – {prog_name}\n\n")
        f.write("*Fichier analysé :*\n\n")
        f.write(f"`{prog_name}`\n\n")

        # Sommaire
        write_table_of_contents(f)

        # Synthèse
        s = analysis.stats
        f.write("## Synthèse générale\n\n")
        f.write(f"- Nombre de paragraphes : **{s['nb_paragraphs']}**\n")
        f.write(f"- Appels internes (GO TO/PERFORM) : **{s['nb_calls_total']}**\n")
        f.write(f"- Points de sortie : **{s['nb_exit_events']}**\n\n")

        # Graphe logique
        f.write("### Graphe logique d'exécution\n\n")
        f.write("Le graphe logique d'exécution est généré dans le répertoire des graphes.\n\n")

        # Flux
        write_flow_overview(f, analysis, call_graph)

        # Table des paragraphes → liste à puces
        f.write("## Table des paragraphes\n\n")
        for p in analysis.paragraphs:
            f.write(f"- {p.order} - {p.seq} - `{p.name}`\n")
        f.write("\n")

        # Analyse des risques
        write_risk_analysis(f, analysis, call_graph)

        # Variables + score de propreté
        write_variables_and_cleanliness(f, analysis, call_graph)

        # Détail
        f.write("## Détail par paragraphe\n\n")

        for p in analysis.paragraphs:
            f.write(f"### {p.name}  (seq {p.seq})\n\n")

            callers = analysis.callers_by_target.get(p.name, [])
            succ = sorted(call_graph.get(p.name, []))
            exits = analysis.exits_by_paragraph.get(p.name, [])

            # On sépare juste pour la présentation
            external_exits = [e for e in exits if e.kind == "XCTL"]
            other_exits = [e for e in exits if e.kind != "XCTL"]

            # AUCUN APPEL NI SORTIE
            if not callers and not succ and not external_exits and not other_exits:
                f.write("Aucun appel (entrant ou sortant).\n\n")
                continue

            # Appels entrants
            if callers:
                f.write("**Appelé par :**\n\n")
                for c in callers:
                    f.write(
                        f"- `{c.src_paragraph}` (seq {c.seq}) par **{c.kind}** : "
                        f"`{c.line_text.strip()}`\n"
                    )
                f.write("\n")

            # Appels sortants internes
            if succ:
                f.write("**Appels sortants internes (GO TO / PERFORM) :**\n\n")
                for t in succ:
                    f.write(f"- vers `{t}`\n")
                f.write("\n")

            # Sorties externes (XCTL, etc.)
            if external_exits:
                f.write("**Sorties vers l'extérieur (XCTL / RETURN / GOBACK / STOP RUN) :**\n\n")
                for e in external_exits:
                    f.write(
                        f"- {e.kind} (seq {e.seq}) : "
                        f"`{e.line_text.strip()}`\n"
                    )
                f.write("\n")

            # Autres points de sortie
            if other_exits:
                f.write("**Autres points de sortie :**\n\n")
                for e in other_exits:
                    f.write(
                        f"- {e.kind} (seq {e.seq}) : "
                        f"`{e.line_text.strip()}`\n"
                    )
                f.write("\n")

    return md_path


# ============================================================
#   CLI simple
# ============================================================

def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        print("Usage : report_markdown.py chemin/PROG.cbl.etude [config.yaml]")
        return 1

    etude_path = argv[0]
    config_path = argv[1] if len(argv) > 1 else "config.yaml"

    cfg = load_config(config_path)
    output_dir = cfg.get("output_dir", "./output")

    md_path = make_markdown_report(etude_path, output_dir)
    print(f"Rapport généré : {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
