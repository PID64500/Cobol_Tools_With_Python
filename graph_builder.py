#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
graph_builder.py
----------------
Construit un graphe logique a partir d'un fichier COBOL normalise (.cbl.etude).

- Noeuds :
    * Paragraphes COBOL (classes : init, PFKEY, anomalies, SRHP, autres)
    * Points de sortie (XCTL, RETURN, GOBACK, STOP RUN)

- Arcs :
    * Paragraphe -> Paragraphe (GO TO / PERFORM / PERFORM THRU)
    * Paragraphe -> Sortie (XCTL / RETURN / GOBACK / STOP RUN)

Sortie :
    - Fichier DOT dans output_dir : <programme>_graph.dot

Usage :
    python graph_builder.py chemin/MONPROG.cbl.etude
"""

import sys
import os
import re
import yaml
from dataclasses import dataclass
from typing import List, Dict, Tuple


# ===========================
#   Modeles de donnees
# ===========================

@dataclass
class Paragraph:
    order: int
    seq: str
    name: str
    start_index: int  # indice de la ligne de debut dans le tableau de lignes


@dataclass
class Edge:
    src: str
    dst: str
    kind: str  # "GO TO", "PERFORM", "PERFORM THRU", "XCTL", "RETURN", "GOBACK", "STOP RUN"


# ===========================
#   Utils config
# ===========================

def load_config(config_path: str = "config.yaml") -> Dict:
    """Charge config.yaml pour recuperer output_dir, etc."""
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration introuvable : {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ===========================
#   Extraction paragraphes
# ===========================

def is_paragraph_line(line: str) -> bool:
    """
    Determine si une ligne .etude contient un debut de paragraphe.

    Hypothese format .etude :
      - col 1-6 : sequence
      - col 7-72 : code COBOL
    On considere 'paragraphe' si :
      - col 8 (index 7) non blanche
      - premier token termine par '.'
    """
    if len(line) < 8:
        return False

    if line[7] == " ":
        return False

    code = line[7:72].rstrip()
    if not code:
        return False

    first_token = code.split()[0]
    return first_token.endswith(".")


def extract_paragraphs_with_positions(etude_path: str) -> Tuple[List[str], List[Paragraph]]:
    """
    Lit le .cbl.etude et renvoie :
      - la liste des lignes normalisees
      - la liste des Paragraph avec index de debut

    Ne prend les paragraphes qu'apres 'PROCEDURE DIVISION'.
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

        if is_paragraph_line(line):
            seq = line[0:6]
            first_token = code.split()[0]
            name = first_token.rstrip(".")
            paragraphs.append(Paragraph(order, seq, name, idx))
            order += 1

    return lines, paragraphs


# ===========================
#   Analyse des lignes / edges
# ===========================

# Regex pour extraire PROGRAM('XXX') et TRANSID('XXX')
RE_PROGRAM = re.compile(r"PROGRAM\(['\"]([^'\"]+)['\"]\)", re.IGNORECASE)
RE_TRANSID = re.compile(r"TRANSID\(['\"]([^'\"]+)['\"]\)", re.IGNORECASE)


def normalize_target_name(raw: str, para_names: set) -> str:
    """
    Normalise un nom de cible (GO TO / PERFORM) pour essayer
    de le faire correspondre a un paragraphe existant.

    - supprime le '.' final
    - si termine par '-F', essaye sans le '-F'
    """
    base = raw.rstrip(".")
    if base in para_names:
        return base

    if base.endswith("-F"):
        cand = base[:-2]
        if cand in para_names:
            return cand

    return ""


def add_internal_edges_for_paragraph(lines: List[str],
                                     paragraphs_by_name: Dict[str, Paragraph],
                                     p: Paragraph,
                                     next_start_index: int,
                                     edges: List[Edge]) -> None:
    """
    Ajoute les arcs internes (GO TO / PERFORM) pour un paragraphe donne,
    y compris :
      - PERFORM X
      - PERFORM X THRU Y
      - PERFORM X-F
    """
    start = p.start_index + 1
    end = next_start_index

    para_names = set(paragraphs_by_name.keys())

    for i in range(start, end):
        code = lines[i][7:72].strip()
        if not code:
            continue

        upper = code.upper()
        tokens = code.replace(".", " ").split()
        upper_tokens = upper.replace(".", " ").split()

        # ----- GO TO -----
        if "GO" in upper_tokens and "TO" in upper_tokens:
            try:
                idx_to = upper_tokens.index("TO")
                raw_target = tokens[idx_to + 1]
                target = normalize_target_name(raw_target, para_names)
                if target:
                    edges.append(Edge(src=p.name, dst=target, kind="GO TO"))
            except Exception:
                pass

        # ----- PERFORM -----
        if "PERFORM" in upper_tokens:
            try:
                idx_p = upper_tokens.index("PERFORM")
                raw_target = tokens[idx_p + 1]
                target = normalize_target_name(raw_target, para_names)

                # On ignore les PERFORM SMAD-xxxx (traces)
                if target and not target.upper().startswith("SMAD-"):
                    edges.append(Edge(src=p.name, dst=target, kind="PERFORM"))

                # Cas PERFORM X THRU Y
                if "THRU" in upper_tokens:
                    try:
                        idx_t = upper_tokens.index("THRU")
                        raw_target2 = tokens[idx_t + 1]
                        target2 = normalize_target_name(raw_target2, para_names)
                        if target2 and not target2.upper().startswith("SMAD-"):
                            edges.append(Edge(src=p.name, dst=target2, kind="PERFORM THRU"))
                    except Exception:
                        pass

            except Exception:
                pass


def add_exit_edges_for_paragraph(lines: List[str],
                                 p: Paragraph,
                                 next_start_index: int,
                                 edges: List[Edge],
                                 exit_nodes: Dict[str, str]) -> None:
    """
    Ajoute les arcs vers les sorties (XCTL, RETURN, GOBACK, STOP RUN)
    pour un paragraphe donne.
    exit_nodes sert de map label -> type.
    """
    start = p.start_index + 1
    end = next_start_index

    for i in range(start, end):
        code = lines[i][7:72].rstrip()
        if not code:
            continue

        up = code.upper()
        tokens = up.split()

        # EXEC CICS XCTL
        if "EXEC CICS" in up and "XCTL" in up:
            m = RE_PROGRAM.search(code)
            if m:
                prog = m.group(1)
                label = f"XCTL {prog}"
            else:
                label = "XCTL"
            exit_nodes[label] = "XCTL"
            edges.append(Edge(src=p.name, dst=label, kind="XCTL"))

        # EXEC CICS RETURN
        if "EXEC CICS" in up and "RETURN" in up:
            m_t = RE_TRANSID.search(code)
            if m_t:
                trans = m_t.group(1)
                label = f"RETURN {trans}"
            else:
                label = "RETURN"
            exit_nodes[label] = "RETURN"
            edges.append(Edge(src=p.name, dst=label, kind="RETURN"))

        # GOBACK
        if "GOBACK" in tokens:
            label = "GOBACK"
            exit_nodes[label] = "GOBACK"
            edges.append(Edge(src=p.name, dst=label, kind="GOBACK"))

        # STOP RUN
        if "STOP" in tokens and "RUN" in tokens:
            label = "STOP RUN"
            exit_nodes[label] = "STOP RUN"
            edges.append(Edge(src=p.name, dst=label, kind="STOP RUN"))


def build_graph(etude_path: str) -> Tuple[List[Paragraph], List[Edge], Dict[str, str]]:
    """
    Construit la liste des paragraphes, des edges (internes + sorties),
    et la map des noeuds de sortie (label -> type).
    """
    lines, paragraphs = extract_paragraphs_with_positions(etude_path)

    paragraphs_by_name = {p.name: p for p in paragraphs}
    edges: List[Edge] = []
    exit_nodes: Dict[str, str] = {}  # label -> type

    for idx, p in enumerate(paragraphs):
        next_start = paragraphs[idx + 1].start_index if idx + 1 < len(paragraphs) else len(lines)

        # Arcs internes (GO TO / PERFORM)
        add_internal_edges_for_paragraph(lines, paragraphs_by_name, p, next_start, edges)

        # Arcs vers sorties (XCTL, RETURN, GOBACK, STOP RUN)
        add_exit_edges_for_paragraph(lines, p, next_start, edges, exit_nodes)

    return paragraphs, edges, exit_nodes


# ===========================
#   Classification visuelle
# ===========================

def classify_paragraph(name: str) -> str:
    """
    Renvoie une classe de noeud pour la mise en forme graphique.
    """
    u = name.upper()

    if name.startswith("000-") or "INIT" in u:
        return "init"
    if "PF" in u:
        return "pfkey"
    if u.startswith("SRHP-"):
        return "srhp"
    if "ANO" in u or "ANOM" in u or "ZZ" in u:
        return "anomaly"
    return "other"


# ===========================
#   Generation DOT
# ===========================

def write_dot_file(dot_path: str,
                   paragraphs: List[Paragraph],
                   edges: List[Edge],
                   exit_nodes: Dict[str, str]) -> None:
    """
    Ecrit un fichier DOT representant le graphe logique, avec
    une mise en forme "premium" (clusters, couleurs, styles).
    """
    # Regrouper les paragraphes par classe
    classes: Dict[str, List[str]] = {
        "init": [],
        "pfkey": [],
        "anomaly": [],
        "srhp": [],
        "other": [],
    }

    for p in paragraphs:
        cls = classify_paragraph(p.name)
        classes.setdefault(cls, []).append(p.name)

    with open(dot_path, "w", encoding="utf-8") as f:
        f.write("digraph G {\n")
        f.write("  rankdir=LR;\n")
        f.write('  graph [fontsize=10, fontname="Arial"];\n')
        f.write('  node  [fontname="Arial", style="rounded,filled", fontsize=10];\n')
        f.write('  edge  [fontname="Arial", fontsize=9];\n\n')

        # --- Clusters paragraphes ---
        def emit_cluster(name: str, label: str, color: str, node_names: List[str]):
            if not node_names:
                return
            f.write(f'  subgraph cluster_{name} {{\n')
            f.write(f'    label="{label}";\n')
            f.write(f'    color="{color}";\n')
            f.write('    style="rounded";\n')
            for n in node_names:
                # Couleur de remplissage par cluster
                fill = "#ffffff"
                if name == "init":
                    fill = "#e0f7e9"     # vert clair
                elif name == "pfkey":
                    fill = "#e0ecff"     # bleu clair
                elif name == "anomaly":
                    fill = "#ffe9d6"     # orange clair
                elif name == "srhp":
                    fill = "#f0e5ff"     # violet tres clair
                else:
                    fill = "#f5f5f5"     # gris clair

                f.write(f'    "{n}" [shape=box, fillcolor="{fill}"];\n')
            f.write("  }\n\n")

        emit_cluster("init", "Initialisation", "#66bb6a", classes.get("init", []))
        emit_cluster("pfkey", "Traitement PFKEY / commandes utilisateur", "#42a5f5", classes.get("pfkey", []))
        emit_cluster("anomaly", "Gestion des anomalies", "#ff7043", classes.get("anomaly", []))
        emit_cluster("srhp", "Bloc SRHP / traitements communs", "#ab47bc", classes.get("srhp", []))
        emit_cluster("other", "Autres paragraphes", "#9e9e9e", classes.get("other", []))

        # --- Noeuds de sortie ---
        if exit_nodes:
            f.write('  subgraph cluster_exits {\n')
            f.write('    label="Sorties CICS / Programme";\n')
            f.write('    color="#e53935";\n')
            f.write('    style="rounded";\n')
            for label, kind in sorted(exit_nodes.items()):
                f.write(
                    f'    "{label}" [shape=doublecircle, '
                    f'fillcolor="#ffebee", '
                    f'color="#e53935", '
                    f'penwidth=1.5];\n'
                )
            f.write("  }\n\n")

        # --- Arcs ---
        for e in edges:
            # Style different selon le type de lien
            attrs = []
            attrs.append(f'label="{e.kind}"')

            if e.kind in ("GO TO",):
                attrs.append('style="dashed"')
                attrs.append('color="#666666"')
            elif e.kind.startswith("PERFORM"):
                attrs.append('style="solid"')
                attrs.append('color="#444444"')
            else:  # sorties
                attrs.append('color="#e53935"')
                attrs.append('penwidth=1.3')

            attr_txt = ", ".join(attrs)
            f.write(f'  "{e.src}" -> "{e.dst}" [{attr_txt}];\n')

        f.write("}\n")


# ===========================
#   main
# ===========================

def main():
    if len(sys.argv) != 2:
        print("Usage : python graph_builder.py <fichier.cbl.etude>")
        sys.exit(1)

    etude_path = sys.argv[1]
    if not os.path.exists(etude_path):
        print(f"[ERREUR] Fichier introuvable : {etude_path}")
        sys.exit(1)

    # Config pour output_dir
    config = load_config("config.yaml")
    output_dir = os.path.abspath(config.get("output_dir", "./output"))
    os.makedirs(output_dir, exist_ok=True)

    # Construction du graphe
    paragraphs, edges, exit_nodes = build_graph(etude_path)

    prog_name = os.path.basename(etude_path).replace(".cbl.etude", "")
    dot_path = os.path.join(output_dir, f"{prog_name}_graph.dot")

    write_dot_file(dot_path, paragraphs, edges, exit_nodes)

    print(f"[OK] Graphe DOT genere : {dot_path}")
    print('    Rendu : dot -Tpng "{0}" -o "{1}_graph.png"'.format(dot_path, prog_name))


if __name__ == "__main__":
    main()
