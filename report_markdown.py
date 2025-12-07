#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
report_markdown.py
------------------
Génère un rapport Markdown pour un programme COBOL (.cbl.etude)
en s'appuyant sur analysis_core.py.

NOUVEAUTÉS :
    - Synthèse générale enrichie
    - Vue synthétique des flux (call graph)
    - Analyse des risques structurels
    - Interprétation fonctionnelle automatique
    - Détail par paragraphe :
        * Appels entrants
        * Appels sortants
        * Sorties CICS / programme

Usage :
    python report_markdown.py chemin/MONPROG.cbl.etude

Sortie :
    <output_dir>/<MONPROG>_report.md
"""

import os
import sys
from typing import Dict, List, Set

import yaml

import logging
logger = logging.getLogger(__name__)

from analysis_core import (
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
    """
    Charge config.yaml si présent, sinon renvoie un dict minimal.
    """
    if not os.path.exists(config_path):
        return {
            "output_dir": "./output"
        }
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def classify_paragraph(name: str) -> str:
    """
    Classe visuelle / fonctionnelle du paragraphe, pour le report.
    Purement heuristique mais utile pour l'audit.
    """
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
#   Construction du graphe d'appels (sortants)
# ============================================================

def build_call_graph(analysis: AnalysisResult) -> Dict[str, Set[str]]:
    """
    Construit un graphe d'appels "sortants" à partir des callers_by_target.

    callers_by_target : { target : [Caller(src_paragraph, ...), ...] }

    On veut :
        call_graph : { source : {target1, target2, ...} }
    """
    call_graph: Dict[str, Set[str]] = {
        p.name: set() for p in analysis.paragraphs
    }

    for target, callers in analysis.callers_by_target.items():
        for c in callers:
            call_graph.setdefault(c.src_paragraph, set()).add(target)

    return call_graph


# ============================================================
#   Sections avancées du rapport
# ============================================================

def write_table_of_contents(f):
    """
    Écrit une petite table des matières (liens Markdown simples).
    Les ancres dépendent du viewer, mais même sans liens cliquables
    ça sert de sommaire rapide.
    """
    f.write("## Sommaire\n\n")
    f.write("- [Synthèse générale](#synthèse-générale)\n")
    f.write("- [Vue synthétique des flux](#vue-synthétique-des-flux)\n")
    f.write("- [Table des paragraphes](#table-des-paragraphes)\n")
    f.write("- [Points d'entrée potentiels](#points-dentrée-potentiels)\n")
    f.write("- [Analyse des risques](#analyse-des-risques)\n")
    f.write("- [Interprétation fonctionnelle](#interprétation-fonctionnelle)\n")
    f.write("- [Détail par paragraphe](#détail-par-paragraphe)\n")
    f.write("- [Résumé exécutif (version courte)](#résumé-exécutif-version-courte)\n\n")


def write_flow_overview(f, analysis: AnalysisResult, call_graph: Dict[str, Set[str]]):
    """
    Écrit une vue synthétique des flux logiques à partir des points d'entrée.
    On ne cherche pas l'exhaustivité des scénarios, mais une vision globale lisible.
    """
    f.write("## Vue synthétique des flux\n\n")

    if not analysis.entry_points:
        f.write(
            "Aucun point d'entrée évident (chaque paragraphe est appelé "
            "par au moins un autre). La détermination des flux devra "
            "s'appuyer sur le JCL ou les transactions CICS.\n\n"
        )
        return

    for ep in analysis.entry_points:
        f.write(f"### Flux à partir de `{ep}`\n\n")
        visited: Set[str] = set()
        queue: List[str] = [ep]

        while queue:
            src = queue.pop(0)
            if src in visited:
                continue
            visited.add(src)

            succ = sorted(call_graph.get(src, []))
            if not succ:
                continue

            succ_list = ", ".join(f"`{t}`" for t in succ)
            f.write(f"- `{src}` → {succ_list}\n")

            for t in succ:
                if t not in visited:
                    queue.append(t)

        f.write("\n")


def write_risk_analysis(f, analysis: AnalysisResult, call_graph: Dict[str, Set[str]]):
    """
    Détecte et commente quelques patterns de risque dans la structure du programme.
    C'est volontairement simple, mais très utile en audit.
    """
    f.write("## Analyse des risques\n\n")

    s = analysis.stats
    risks: List[str] = []

    # 1. Présence de GO TO ?
    if s["nb_goto"] > 0:
        risks.append(
            f"⚠ Le programme contient **{s['nb_goto']}** instructions `GO TO` "
            "→ complexité de lecture accrue et risques de flux difficiles à suivre."
        )

    # 2. Paragraphes avec plusieurs sorties
    multi_exit_paras = [
        p.name for p in analysis.paragraphs
        if len(analysis.exits_by_paragraph.get(p.name, [])) > 1
    ]
    if multi_exit_paras:
        risks.append(
            "⚠ Certains paragraphes possèdent **plusieurs points de sortie** "
            "(XCTL / RETURN / GOBACK / STOP RUN) : "
            + ", ".join(f"`{n}`" for n in multi_exit_paras)
        )

    # 3. Paragraphes fortement couplés (beaucoup d'appels entrants)
    high_in_degree = [
        p.name for p in analysis.paragraphs
        if len(analysis.callers_by_target.get(p.name, [])) >= 3
    ]
    if high_in_degree:
        risks.append(
            "⚠ Paragraphes très sollicités (>= 3 appels entrants), "
            "potentiellement critiques ou à refactorer : "
            + ", ".join(f"`{n}`" for n in high_in_degree)
        )

    # 4. Paragraphes sans appels entrants et sans sorties → code "isolé"
    isolated = []
    for p in analysis.paragraphs:
        callers = analysis.callers_by_target.get(p.name, [])
        exits = analysis.exits_by_paragraph.get(p.name, [])
        if not callers and not exits:
            isolated.append(p.name)
    if isolated:
        risks.append(
            "ℹ Paragraphes non référencés et sans sortie : "
            "potentiellement du code mort ou réservé à des évolutions : "
            + ", ".join(f"`{n}`" for n in isolated)
        )

    # 5. Paragraphes d'anomalies appelés depuis beaucoup d'endroits
    anomaly_paras = [
        p.name for p in analysis.paragraphs
        if "ANO" in p.name.upper() or "ANOM" in p.name.upper() or "ZZ" in p.name.upper()
    ]
    hotspot_anom = [
        n for n in anomaly_paras
        if len(analysis.callers_by_target.get(n, [])) >= 2
    ]
    if hotspot_anom:
        risks.append(
            "ℹ La gestion d'anomalies est centralisée dans : "
            + ", ".join(f"`{n}`" for n in hotspot_anom)
            + " → bon point pour la lisibilité, mais ces blocs sont critiques."
        )

    if not risks:
        f.write(
            "Aucun risque structurel majeur détecté à partir de la seule analyse "
            "des paragraphes, appels internes et sorties. Des vérifications "
            "complémentaires (tests, logs CICS, JCL) restent nécessaires.\n\n"
        )
    else:
        for r in risks:
            f.write(f"- {r}\n")
        f.write("\n")


def write_functional_interpretation(f, analysis: AnalysisResult):
    """
    Produit un texte d'interprétation fonctionnelle "semi-automatique"
    en se basant sur les familles de paragraphes détectées.
    """
    categories: Dict[str, int] = {}
    for p in analysis.paragraphs:
        cat = classify_paragraph(p.name)
        categories[cat] = categories.get(cat, 0) + 1

    f.write("## Interprétation fonctionnelle\n\n")

    if not categories:
        f.write(
            "La structure des paragraphes ne permet pas de dégager automatiquement "
            "des blocs fonctionnels significatifs. Une analyse manuelle reste "
            "nécessaire.\n\n"
        )
        return

    f.write(
        "À partir des noms de paragraphes et de leur regroupement typologique, "
        "on peut proposer l'interprétation suivante (à confirmer fonctionnellement) :\n\n"
    )

    f.write("Le programme semble organisé autour des blocs suivants :\n\n")
    for cat, count in categories.items():
        f.write(f"- **{cat}** : {count} paragraphe(s)\n")
    f.write("\n")

    # Petit texte générique
    if "Initialisation" in categories:
        f.write(
            "- La présence d'un ou plusieurs paragraphes d'initialisation suggère "
            "une mise en place explicite du contexte de traitement (zones de travail, "
            "lecture de constantes, etc.).\n"
        )
    if "Gestion PFKEY / commande" in categories:
        f.write(
            "- Des paragraphes de gestion PFKEY indiquent une interaction "
            "forte avec l'utilisateur (navigation, choix d'options, "
            "pilotage de la suite des traitements par les touches de fonction).\n"
        )
    if "Bloc commun SRHP" in categories:
        f.write(
            "- Les blocs `SRHP-...` suggèrent des traitements communs factorisés "
            "(sauvegarde de COMMAREA, appels d'interfaces, gestion d'IDMS, etc.).\n"
        )
    if "Gestion d'anomalies" in categories:
        f.write(
            "- Les paragraphes liés aux anomalies (`ANO`, `ANOM`, `ZZ`) concentrent "
            "la gestion des erreurs et des cas exceptionnels ; ils sont souvent "
            "critiques pour la robustesse et doivent être bien documentés.\n"
        )

    f.write("\n")


# ============================================================
#   Génération du rapport complet Markdown
# ============================================================

def make_markdown_report(etude_path: str, output_dir: str) -> str:
    """
    Génère le rapport Markdown pour un .cbl.etude donné.
    Retourne le chemin complet du fichier généré.
    """
    analysis = analyze_program(etude_path)
    call_graph = build_call_graph(analysis)

    prog_name = analysis.program_name
    md_name = f"{prog_name}_report.md"
    os.makedirs(output_dir, exist_ok=True)
    md_path = os.path.join(output_dir, md_name)

    # On suppose que le graphe PNG serait, si présent :
    graph_png = os.path.join(output_dir, f"{prog_name}_graph.png")
    graph_png_rel = os.path.basename(graph_png)

    with open(md_path, "w", encoding="utf-8") as f:
        # Titre
        f.write(f"# Rapport d'analyse COBOL – {prog_name}\n\n")
        f.write(f"*Fichier source analysé :*\n\n")
        f.write(f"`{analysis.etude_path}`\n\n")

        # Sommaire
        write_table_of_contents(f)

        # Synthèse générale
        s = analysis.stats
        f.write("## Synthèse générale\n\n")
        f.write(f"- Nombre de paragraphes : **{s['nb_paragraphs']}**\n")
        f.write(f"- Nombre total d'appels internes (GO TO / PERFORM) : **{s['nb_calls_total']}**\n")
        f.write(f"  - GO TO : **{s['nb_goto']}**\n")
        f.write(f"  - PERFORM : **{s['nb_perform']}**\n")
        f.write(f"  - PERFORM THRU : **{s['nb_perform_thru']}**\n")
        f.write(f"- Nombre de points de sortie CICS / programme : **{s['nb_exit_events']}**\n")
        f.write(f"- Nombre de points d'entrée potentiels : **{len(analysis.entry_points)}**\n\n")

        # Graphe d'exécution si dispo
        if os.path.exists(graph_png):
            f.write("### Graphe logique d'exécution\n\n")
            f.write(f"Le graphe d'exécution a été généré dans le fichier : `{graph_png}`.\n\n")
            f.write(f"![Graphe d'exécution]({graph_png_rel})\n\n")
        else:
            f.write("### Graphe logique d'exécution\n\n")
            f.write(
                "Aucun fichier de graphe PNG détecté. "
                "Si besoin, générez-le avec `graph_builder.py` avant ou après ce rapport.\n\n"
            )

        # Vue synthétique des flux
        write_flow_overview(f, analysis, call_graph)

        # Table des paragraphes
        f.write("## Table des paragraphes\n\n")
        f.write("| Ordre | Seq | Paragraphe | Rôle présumé |\n")
        f.write("|-------|-----|------------|--------------|\n")
        for p in analysis.paragraphs:
            role = classify_paragraph(p.name)
            f.write(f"| {p.order} | {p.seq} | `{p.name}` | {role} |\n")
        f.write("\n")

        # Points d'entrée
        f.write("## Points d'entrée potentiels\n\n")
        if analysis.entry_points:
            for name in analysis.entry_points:
                role = classify_paragraph(name)
                f.write(f"- `{name}` (*{role}*)\n")
            f.write("\n")
        else:
            f.write(
                "_Aucun point d'entrée sans appel détecté (tous les paragraphes sont référencés)._ \n\n"
            )

        # Analyse des risques
        write_risk_analysis(f, analysis, call_graph)

        # Interprétation fonctionnelle
        write_functional_interpretation(f, analysis)

        # Détail par paragraphe
        f.write("## Détail par paragraphe\n\n")
        for p in analysis.paragraphs:
            f.write(f"### {p.name}  (seq {p.seq})\n\n")

            # Appels entrants
            callers = analysis.callers_by_target.get(p.name, [])
            f.write("**Appelé par :**\n\n")
            if callers:
                for c in callers:
                    f.write(
                        f"- `{c.src_paragraph}` (seq {c.seq}) via **{c.kind}** : "
                        f"`{c.line_text.strip()}`\n"
                    )
            else:
                f.write("- (aucun appel direct) → *point d'entrée possible*\n")
            f.write("\n")

            # Appels sortants
            succ = sorted(call_graph.get(p.name, []))
            f.write("**Appels sortants :**\n\n")
            if succ:
                for t in succ:
                    f.write(f"- vers `{t}`\n")
            else:
                f.write("- (aucun appel sortant direct vers un autre paragraphe)\n")
            f.write("\n")

            # Sorties
            exits = analysis.exits_by_paragraph.get(p.name, [])
            f.write("**Sorties CICS / fin de programme dans ce paragraphe :**\n\n")
            if exits:
                for e in exits:
                    f.write(
                        f"- [{e.kind}] {e.label} (seq {e.seq}) : "
                        f"`{e.line_text.strip()}`\n"
                    )
            else:
                f.write("- (aucune sortie détectée dans ce paragraphe)\n")
            f.write("\n")

        # Mini conclusion / résumé exécutif
        f.write("---\n\n")
        f.write("### Résumé exécutif (version courte)\n\n")
        f.write(
            "Ce rapport fournit une vue structurée d'un programme COBOL existant : "
            "paragraphes, appels internes et points de sortie CICS. "
            "Il permet de comprendre rapidement l'organisation du code, "
            "d'identifier les points d'entrée probables, les blocs de traitement "
            "et la localisation de la gestion des anomalies. "
            "Les risques mis en évidence (usage de GO TO, multiplicités de sorties, "
            "paragraphes très sollicités) constituent de bons candidats pour des "
            "actions de refactorisation ou de sécurisation.\n"
        )

    return md_path


# ============================================================
#   Programme principal
# ============================================================

def main():
    if len(sys.argv) != 2:
        print("Usage : python report_markdown.py chemin/MONPROG.cbl.etude")
        sys.exit(1)

    etude_path = sys.argv[1]
    if not os.path.exists(etude_path):
        print(f"[ERREUR] Fichier introuvable : {etude_path}")
        sys.exit(1)

    config = load_config("config.yaml")
    output_dir = os.path.abspath(config.get("output_dir", "./output"))

    md_path = make_markdown_report(etude_path, output_dir)
    print(f"[OK] Rapport Markdown généré : {md_path}")


if __name__ == "__main__":
    main()
