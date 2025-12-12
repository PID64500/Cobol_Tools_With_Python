#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
generate_global_synthesis.py
----------------------------

Analyse un ensemble de fichiers COBOL normalisés (.cbl.etude)
et produit :

- un CSV global (global_metrics.csv) avec les métriques principales
  par programme,
- un rapport Markdown de synthèse (audit_synthese_global.md)
  avec :
    * rappel de la méthodologie,
    * synthèse des risques,
    * agrégats chiffrés,
    * top des programmes les plus complexes.
"""

import sys
import csv
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Set, Tuple
from datetime import datetime

from analysis_core_wrapper import analyze_program, AnalysisResult


# ============================================================
#   Outils graphe (copié depuis report_markdown)
# ============================================================

def build_call_graph(analysis: AnalysisResult) -> Dict[str, Set[str]]:
    call_graph: Dict[str, Set[str]] = {p.name: set() for p in analysis.paragraphs}
    for target, callers in analysis.callers_by_target.items():
        for c in callers:
            call_graph.setdefault(c.src_paragraph, set()).add(target)
    return call_graph


def compute_longest_paths(
    entry_points: List[str],
    call_graph: Dict[str, Set[str]],
) -> Tuple[int, List[List[str]]]:
    max_len = 0
    examples: List[List[str]] = []

    def dfs(current: str, stack: List[str]):
        nonlocal max_len, examples
        if current in stack:
            return
        stack.append(current)
        succ = sorted(call_graph.get(current, []))
        if not succ:
            l = len(stack)
            if l > max_len:
                max_len = l
                examples = [stack.copy()]
            elif l == max_len and l > 0 and len(examples) < 5:
                examples.append(stack.copy())
        else:
            for s in succ:
                dfs(s, stack)
        stack.pop()

    for ep in entry_points:
        dfs(ep, [])

    return max_len, examples


def find_cycles(call_graph: Dict[str, Set[str]]) -> List[List[str]]:
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


def compute_cleanliness_score(
    analysis: AnalysisResult,
    call_graph: Dict[str, Set[str]],
) -> int:
    """
    Version simplifiée : renvoie seulement le score (0-100).
    Même logique que dans report_markdown.
    """
    s = analysis.stats
    nb_goto = s.get("nb_goto", 0)
    nb_decl = s.get("nb_variables_declared", 0)
    nb_unused = s.get("nb_variables_unused", 0)
    nb_paras = s.get("nb_paragraphs", 0)

    penalty_goto = min(30, nb_goto * 2)

    ratio_dead = 0.0
    if nb_decl > 0:
        ratio_dead = nb_unused / nb_decl * 100.0
    penalty_deadvars = min(25, int(ratio_dead * 0.3))

    cycles = find_cycles(call_graph)
    penalty_cycles = 15 if cycles else 0

    penalty_depth = 0
    if analysis.entry_points:
        max_len, _ = compute_longest_paths(analysis.entry_points, call_graph)
        if max_len >= 8:
            penalty_depth = 10
        elif max_len >= 6:
            penalty_depth = 5

    penalty_unreachable = 0
    if analysis.entry_points and nb_paras > 0:
        # on ne storage pas le détail ici, seulement la pénalité
        pass

    total_penalty = penalty_goto + penalty_deadvars + penalty_cycles + penalty_depth + penalty_unreachable
    score = max(0, 100 - total_penalty)
    return score


# ============================================================
#   Structure de données globale
# ============================================================

@dataclass
class ProgramMetrics:
    program: str
    path: str
    nb_paragraphs: int
    nb_goto: int
    nb_calls_total: int
    nb_exit_events: int
    depth_max: int
    nb_cycles: int
    nb_variables_declared: int
    nb_variables_unused: int
    cleanliness_score: int


# ============================================================
#   Analyse de N fichiers
# ============================================================

def analyze_files(etude_paths: List[Path]) -> List[ProgramMetrics]:
    metrics: List[ProgramMetrics] = []

    for p in etude_paths:
        analysis = analyze_program(str(p))
        call_graph = build_call_graph(analysis)
        cycles = find_cycles(call_graph)
        depth_max, _ = compute_longest_paths(analysis.entry_points, call_graph)
        score = compute_cleanliness_score(analysis, call_graph)

        s = analysis.stats
        m = ProgramMetrics(
            program=analysis.program_name,
            path=str(p),
            nb_paragraphs=s.get("nb_paragraphs", 0),
            nb_goto=s.get("nb_goto", 0),
            nb_calls_total=s.get("nb_calls_total", 0),
            nb_exit_events=s.get("nb_exit_events", 0),
            depth_max=depth_max,
            nb_cycles=len(cycles),
            nb_variables_declared=s.get("nb_variables_declared", 0),
            nb_variables_unused=s.get("nb_variables_unused", 0),
            cleanliness_score=score,
        )
        metrics.append(m)

    return metrics


# ============================================================
#   Export CSV
# ============================================================

def write_csv(metrics: List[ProgramMetrics], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "global_metrics.csv"

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow([
            "Programme",
            "Chemin",
            "Nb_paragraphes",
            "Nb_GOTO",
            "Nb_appels_totaux",
            "Nb_points_sortie",
            "Profondeur_max",
            "Nb_cycles",
            "Nb_var_decl",
            "Nb_var_inutiles",
            "Score_proprete",
        ])
        for m in metrics:
            writer.writerow([
                m.program,
                m.path,
                m.nb_paragraphs,
                m.nb_goto,
                m.nb_calls_total,
                m.nb_exit_events,
                m.depth_max,
                m.nb_cycles,
                m.nb_variables_declared,
                m.nb_variables_unused,
                m.cleanliness_score,
            ])

    return csv_path


# ============================================================
#   Synthèse Markdown globale
# ============================================================

def write_global_markdown(metrics: List[ProgramMetrics], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / "audit_synthese_global.md"

    n = len(metrics)
    date_str = datetime.now().strftime("%Y-%m-%d")

    if n == 0:
        content = "# Synthèse globale\n\nAucun programme analysé.\n"
        md_path.write_text(content, encoding="utf-8")
        return md_path

    # Agrégats simples
    avg_goto = sum(m.nb_goto for m in metrics) / n
    avg_depth = sum(m.depth_max for m in metrics) / n
    avg_score = sum(m.cleanliness_score for m in metrics) / n

    nb_with_goto = sum(1 for m in metrics if m.nb_goto > 0)
    nb_with_cycles = sum(1 for m in metrics if m.nb_cycles > 0)
    nb_low_score = sum(1 for m in metrics if m.cleanliness_score < 60)

    # Top 10 les plus "critiques" = score de propreté le plus bas
    worst = sorted(metrics, key=lambda m: m.cleanliness_score)[:10]

    lines: List[str] = []

    lines.append(f"# Synthèse globale d'analyse COBOL\n")
    lines.append(f"*Date : {date_str}*\n")
    lines.append(f"*Nombre de programmes analysés : **{n}***\n")
    lines.append("\n")

    # Rappel très court de la méthode
    lines.append("## Méthodologie (rappel synthétique)\n\n")
    lines.append(
        "- Analyse statique des sources COBOL normalisées (`.cbl.etude`).\n"
        "- Reconstruction des paragraphes, appels internes (`PERFORM`, `GO TO`).\n"
        "- Recensement des points de sortie (`RETURN`, `GOBACK`, `STOP RUN`, `XCTL`).\n"
        "- Calcul d'indicateurs de complexité (profondeur des chaînes d'appel, cycles).\n"
        "- Mesure d'un score de propreté global par programme (0–100).\n\n"
    )

    # Synthèse chiffrée
    lines.append("## Synthèse chiffrée globale\n\n")
    lines.append(f"- Nombre de programmes analysés : **{n}**\n")
    lines.append(f"- GO TO moyens par programme : **{avg_goto:.1f}**\n")
    lines.append(f"- Profondeur moyenne des chaînes d'appel : **{avg_depth:.1f}** paragraphe(s)\n")
    lines.append(f"- Score moyen de propreté : **{avg_score:.1f}/100**\n")
    lines.append(f"- Programmes contenant au moins un `GO TO` : **{nb_with_goto}**\n")
    lines.append(f"- Programmes présentant au moins un cycle d'appel : **{nb_with_cycles}**\n")
    lines.append(f"- Programmes avec un score de propreté < 60 : **{nb_low_score}**\n\n")

    # Risques analysés (texte générique, aligné avec notre discussion)
    lines.append("## Catégories de risques analysées\n\n")
    lines.append(
        "- **Usage de `GO TO`** : flux peu structurés, complexité de lecture accrue.\n"
        "- **Paragraphes avec plusieurs sorties** : logique dispersée, comportements difficiles à maîtriser.\n"
        "- **Paragraphes très sollicités / hubs** : forte sensibilité aux évolutions.\n"
        "- **Paragraphes isolés ou inaccessibles** : code mort ou flux non documentés.\n"
        "- **Chaînes d'appel longues** : profondeur importante, compréhension difficile.\n"
        "- **Cycles dans les appels** : risques de boucles logiques.\n"
        "- **Variables déclarées mais inutilisées** : bruit et dette technique.\n\n"
    )

    # Top programmes les plus critiques
    lines.append("## Programmes les plus critiques (score le plus faible)\n\n")
    lines.append("| Programme | Score | Nb GOTO | Prof. max | Nb cycles |\n")
    lines.append("|-----------|-------|---------|-----------|-----------|\n")
    for m in worst:
        lines.append(
            f"| `{m.program}` | {m.cleanliness_score} | {m.nb_goto} | "
            f"{m.depth_max} | {m.nb_cycles} |\n"
        )
    lines.append("\n")

    # Référence au CSV
    lines.append("## Détail complet\n\n")
    lines.append(
        "Le fichier `global_metrics.csv` fournit le détail des indicateurs "
        "pour chaque programme (un programme par ligne).\n"
    )

    md_path.write_text("".join(lines), encoding="utf-8")
    return md_path


# ============================================================
#   CLI
# ============================================================

def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        print(
            "Usage : generate_global_synthesis.py <dir_etudes> "
            "ou generate_global_synthesis.py file1.cbl.etude file2.cbl.etude ..."
        )
        return 1

    # Cas 1 : premier argument = répertoire
    first = Path(argv[0])
    if first.is_dir():
        etude_paths = sorted(first.glob("*.cbl.etude"))
    else:
        etude_paths = [Path(a) for a in argv]

    if not etude_paths:
        print("Aucun fichier .cbl.etude trouvé.")
        return 1

    output_dir = Path("output")

    metrics = analyze_files(etude_paths)
    csv_path = write_csv(metrics, output_dir)
    md_path = write_global_markdown(metrics, output_dir)

    print(f"CSV global généré : {csv_path}")
    print(f"Rapport global Markdown généré : {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
