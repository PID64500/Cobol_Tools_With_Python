#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
scan_exits.py
-------------
A partir d'un fichier COBOL normalise (.cbl.etude),
pour chaque paragraphe, liste les points de sortie :

  - EXEC CICS XCTL ...
  - EXEC CICS RETURN ...
  - GOBACK
  - STOP RUN

Ecrit egalement un log dans output_dir/<programme>_exits.log
"""

import sys
import os
import yaml
from dataclasses import dataclass
from typing import List, Dict


# ============== Modeles ==============

@dataclass
class Paragraph:
    order: int
    seq: str
    name: str
    start_index: int


@dataclass
class ExitPoint:
    seq: str
    exit_type: str
    code: str


# ============== Utils Config ==============

def load_config(config_path: str = "config.yaml") -> Dict:
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration introuvable : {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ============== Extraction Paragraphes ==============

def is_paragraph_line(line: str) -> bool:
    if len(line) < 8:
        return False
    if line[7] == " ":
        return False
    code = line[7:72].rstrip()
    if not code:
        return False
    first_token = code.split()[0]
    return first_token.endswith(".")


def extract_paragraphs_with_positions(etude_path: str):
    with open(etude_path, "r", encoding="latin-1", errors="ignore") as f:
        raw_lines = [ln.rstrip("\n") for ln in f]

    # Normalisation longueur
    lines = [ln.ljust(72) if len(ln) < 72 else ln[:72] for ln in raw_lines]

    paragraphs = []
    in_procedure = False
    order = 1

    for idx, line in enumerate(lines):
        code = line[7:72].strip()

        if code.upper().startswith("PROCEDURE DIVISION"):
            in_procedure = True
            continue

        if not in_procedure:
            continue

        if is_paragraph_line(line):
            seq = line[0:6]
            name = code.split()[0].rstrip(".")
            paragraphs.append(Paragraph(order, seq, name, idx))
            order += 1

    return lines, paragraphs


# ============== Scan des sorties ==============

def scan_exits_in_paragraph(lines, start_idx, end_idx):
    exits = []
    for i in range(start_idx, end_idx):
        line = lines[i]
        seq = line[0:6]
        code = line[7:72].rstrip()
        if not code:
            continue

        up = code.upper()
        tokens = up.split()

        if "EXEC CICS" in up and "XCTL" in up:
            exits.append(ExitPoint(seq, "XCTL", code))

        if "EXEC CICS" in up and "RETURN" in up:
            exits.append(ExitPoint(seq, "RETURN", code))

        if "GOBACK" in tokens:
            exits.append(ExitPoint(seq, "GOBACK", code))

        if "STOP" in tokens and "RUN" in tokens:
            exits.append(ExitPoint(seq, "STOP RUN", code))

    return exits


def scan_all_exits(etude_path: str):
    lines, paragraphs = extract_paragraphs_with_positions(etude_path)

    result = {p.name: [] for p in paragraphs}

    for idx, p in enumerate(paragraphs):
        start_idx = p.start_index + 1
        end_idx = paragraphs[idx + 1].start_index if idx + 1 < len(paragraphs) else len(lines)
        result[p.name] = scan_exits_in_paragraph(lines, start_idx, end_idx)

    return paragraphs, result


# ============== Impression + Log ==============

def build_report_text(etude_path, paragraphs, exits_dict):
    prog = os.path.basename(etude_path)
    out = []
    out.append(f"# Points de sortie detectes par paragraphe")
    out.append(f"# Fichier : {prog}\n")

    for p in paragraphs:
        out.append(f"Paragraphe {p.name} (seq {p.seq})")
        plist = exits_dict.get(p.name, [])
        if not plist:
            out.append("  Sorties : (aucune detectee)\n")
        else:
            out.append("  Sorties :")
            for e in plist:
                out.append(f"    - {e.seq}  {e.exit_type:8s}  {e.code}")
            out.append("")  # ligne vide

    return "\n".join(out)


def main():
    if len(sys.argv) != 2:
        print("Usage : python scan_exits.py <fichier.cbl.etude>")
        sys.exit(1)

    etude_path = sys.argv[1]

    # Charger config.yaml
    config = load_config("config.yaml")
    output_dir = os.path.abspath(config.get("output_dir", "./output"))
    os.makedirs(output_dir, exist_ok=True)

    # Analyse
    paragraphs, exits_dict = scan_all_exits(etude_path)
    report_text = build_report_text(etude_path, paragraphs, exits_dict)

    # Affichage console
    print(report_text)

    # Écriture fichier log
    prog_name = os.path.basename(etude_path).replace(".cbl.etude", "")
    log_path = os.path.join(output_dir, f"{prog_name}_exits.log")

    with open(log_path, "w", encoding="latin-1") as f:
        f.write(report_text)

    print(f"\n[OK] Log ecrit : {log_path}")


if __name__ == "__main__":
    main()
