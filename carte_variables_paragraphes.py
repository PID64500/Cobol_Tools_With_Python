#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
carte_variables_paragraphes.py
------------------------------

Niveau 2.3 - Carte Variable ↔ Paragraphe
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Construit la carte Variable ↔ Paragraphe pour un programme COBOL."
    )
    parser.add_argument("etude_path", help="Chemin du fichier .etude")
    parser.add_argument("usage_csv", help="CSV d'usage (sortie de scan_variable_usage.py)")
    parser.add_argument(
        "--out",
        default="variables_paragraphes.csv",
        help="CSV de sortie (défaut : variables_paragraphes.csv)",
    )
    return parser.parse_args()


def extract_code_part(line: str) -> str:
    if len(line) <= 6:
        return ""
    return line[6:].rstrip("\n")


def load_usage(usage_csv: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with usage_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def build_name_patterns(entries: List[Dict[str, str]]) -> Dict[str, re.Pattern]:
    patterns: Dict[str, re.Pattern] = {}
    for e in entries:
        name = (e.get("name") or "").upper().strip()
        if not name:
            continue
        if name in patterns:
            continue
        pat = re.compile(
            r"(?<![A-Z0-9-])" + re.escape(name) + r"(?![A-Z0-9-])",
            re.IGNORECASE,
        )
        patterns[name] = pat
    return patterns


def detect_paragraph_name(raw_line: str) -> Optional[str]:
    """
    Détection stricte d’un paragraphe COBOL :

      - colonnes 1–6 : numéros → ignorés
      - colonne 7 : indicateur → ignoré (mais on vérifie le '*')
      - colonne 8 : doit contenir le 1er caractère du paragraphe (pas un espace)
      - on lit depuis col.8 jusqu'au premier espace → token
      - token doit finir par '.'
      - longueur du nom (sans '.') <= 30
      - ne doit pas être un mot-clé COBOL / END-xxx
    """
    if len(raw_line) < 8:
        return None

    # colonne 7 = '*' → ligne de commentaire COBOL
    if raw_line[6:7] == "*":
        return None

    code_area = raw_line[7:]  # à partir de la colonne 8

    if not code_area:
        return None

    # Si la colonne 8 est un espace → ce n’est PAS un paragraphe (code indenté)
    if code_area[0].isspace():
        return None

    # Token à partir de col.8 jusqu’au premier espace
    token = code_area.split()[0]  # ex : "100-INITIALISATION."

    # Doit se terminer par un point
    if not token.endswith("."):
        return None

    # On enlève le point
    name = token[:-1]

    # Longueur max 30, non vide
    if not name or len(name) > 30:
        return None

    keywords = {
        "IF", "MOVE", "PERFORM", "CALL", "EVALUATE", "ADD", "SUBTRACT",
        "MULTIPLY", "DIVIDE", "COMPUTE", "GO", "DISPLAY", "ACCEPT",
        "EXEC", "OPEN", "CLOSE", "READ", "WRITE", "REWRITE", "DELETE",
        "SEARCH", "SET", "STRING", "UNSTRING", "INSPECT", "EXIT",
        "CONTINUE", "GOBACK", "STOP",
        "END-EXEC", "END-IF", "END-PERFORM",
    }

    if name.upper() in keywords:
        return None

    return name


def build_var_paragraph_map(
    etude_path: Path,
    usage_rows: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    entries = [e for e in usage_rows if (e.get("level") or "").strip() != "88"]

    patterns = build_name_patterns(entries)

    entries_by_name: Dict[str, List[Dict[str, str]]] = {}
    for e in entries:
        name = (e.get("name") or "").upper().strip()
        if not name:
            continue
        entries_by_name.setdefault(name, []).append(e)

    # clé = (program, section, source, name, full_path, paragraph)
    stats: Dict[Tuple[str, str, str, str, str, str], Dict[str, int]] = {}

    def get_key(entry: Dict[str, str], paragraph: str) -> Tuple[str, str, str, str, str, str]:
        program = (entry.get("program") or "").upper()
        section = (entry.get("section") or "").upper()
        source = (entry.get("source") or "")
        name = (entry.get("name") or "").upper()
        fp = (entry.get("full_path") or name).upper()
        para = paragraph or ""
        return (program, section, source, name, fp, para)

    lines = etude_path.read_text(encoding="latin-1", errors="ignore").splitlines()

    in_procedure = False
    current_paragraph: Optional[str] = None

    for raw in lines:
        code = extract_code_part(raw)
        if not code.strip():
            continue

        uc = code.upper()

        if not in_procedure and "PROCEDURE DIVISION" in uc:
            in_procedure = True

        if not in_procedure:
            continue

        if code.lstrip().startswith("*"):
            continue

        # paragraphe détecté sur la ligne brute
        para = detect_paragraph_name(raw)
        if para:
            current_paragraph = para

        is_cond_line = bool(re.search(r"\b(IF|EVALUATE|WHEN|UNTIL|WHILE)\b", uc))
        is_io_line = bool(re.search(r"\b(READ|WRITE|REWRITE|DELETE|OPEN|CLOSE)\b", uc)) or (
            "EXEC CICS" in uc and ("SEND" in uc or "RECEIVE" in uc)
        )

        idx_move = uc.find("MOVE ")
        idx_to = uc.find(" TO ") if idx_move != -1 else -1

        for name, pat in patterns.items():
            for m in pat.finditer(code):
                start_pos = m.start()

                for e in entries_by_name.get(name.upper(), []):
                    key = get_key(e, current_paragraph or "")
                    st = stats.get(key)
                    if not st:
                        st = {
                            "nb_occurrences": 0,
                            "nb_reads": 0,
                            "nb_writes": 0,
                            "nb_conditions": 0,
                            "nb_io": 0,
                        }
                        stats[key] = st

                    st["nb_occurrences"] += 1

                    if is_cond_line:
                        st["nb_conditions"] += 1

                    if is_io_line:
                        st["nb_io"] += 1

                    if idx_move != -1 and idx_to != -1 and idx_move < idx_to:
                        if start_pos > idx_to:
                            st["nb_writes"] += 1
                        else:
                            st["nb_reads"] += 1
                    else:
                        st["nb_reads"] += 1

    results: List[Dict[str, str]] = []

    for key, st in stats.items():
        program, section, source, name, fp, paragraph = key

        level = ""
        pic = ""
        root_name = fp.split("/")[0] if "/" in fp else fp
        for e in entries_by_name.get(name, []):
            e_fp = (e.get("full_path") or e.get("name") or "").upper()
            if e_fp == fp:
                level = (e.get("level") or "")
                pic = (e.get("pic") or "")
                break

        nb_reads = st["nb_reads"]
        nb_writes = st["nb_writes"]
        nb_cond = st["nb_conditions"]
        nb_io = st["nb_io"]

        usage_parts = []
        if nb_reads > 0:
            usage_parts.append("R")
        if nb_writes > 0:
            usage_parts.append("W")
        if nb_cond > 0:
            usage_parts.append("COND")
        if nb_io > 0:
            usage_parts.append("IO")
        usage_summary = "+".join(usage_parts) if usage_parts else ""

        results.append(
            {
                "program": program,
                "section": section,
                "source": source,
                "root_name": root_name,
                "name": name,
                "full_path": fp,
                "level": level,
                "pic": pic,
                "paragraph": paragraph,
                "nb_occurrences": str(st["nb_occurrences"]),
                "nb_reads": str(nb_reads),
                "nb_writes": str(nb_writes),
                "nb_conditions": str(nb_cond),
                "nb_io": str(nb_io),
                "usage_summary": usage_summary,
            }
        )

    return results


def write_var_paragraph_csv(rows: List[Dict[str, str]], out_csv: Path) -> None:
    if not rows:
        print("[AVERTISSEMENT] Aucune utilisation de variables détectée dans la PROCEDURE DIVISION.")
        return

    fieldnames = [
        "program",
        "section",
        "source",
        "root_name",
        "name",
        "full_path",
        "level",
        "pic",
        "paragraph",
        "nb_occurrences",
        "nb_reads",
        "nb_writes",
        "nb_conditions",
        "nb_io",
        "usage_summary",
    ]

    with out_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def main() -> int:
    args = parse_args()
    etude_path = Path(args.etude_path)
    usage_csv_path = Path(args.usage_csv)
    out_csv_path = Path(args.out)

    if not etude_path.exists():
        print(f"[ERREUR] Fichier .etude introuvable : {etude_path}")
        return 1
    if not usage_csv_path.exists():
        print(f"[ERREUR] Fichier d'usage introuvable : {usage_csv_path}")
        return 1

    usage_rows = load_usage(usage_csv_path)
    if not usage_rows:
        print("[ERREUR] Usage CSV vide.")
        return 1

    rows = build_var_paragraph_map(etude_path, usage_rows)
    write_var_paragraph_csv(rows, out_csv_path)

    print(f"[OK] Carte Variable ↔ Paragraphe générée dans : {out_csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
