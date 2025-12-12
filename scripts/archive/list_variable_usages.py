#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
list_variable_usages.py
-----------------------

Liste détaillée de toutes les utilisations de variables.
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Dict, List, Optional


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Liste toutes les utilisations de toutes les variables dans la PROCEDURE DIVISION."
    )
    parser.add_argument("etude_path", help="Chemin du fichier .etude")
    parser.add_argument("dict_csv", help="CSV du dictionnaire (build_data_dictionary.py)")
    parser.add_argument(
        "--out",
        default="variables_usages_detail.csv",
        help="CSV de sortie (défaut : variables_usages_detail.csv)",
    )
    return parser.parse_args()


def extract_code_part(line: str) -> str:
    if len(line) <= 6:
        return ""
    return line[6:].rstrip("\n")


def load_dictionary(dict_csv: Path) -> List[Dict[str, str]]:
    entries: List[Dict[str, str]] = []
    with dict_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            entries.append(row)
    return entries


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
    Détection stricte d’un paragraphe COBOL (même règle que les autres scripts).
    """
    if len(raw_line) < 8:
        return None

    if raw_line[6:7] == "*":
        return None

    code_area = raw_line[7:]
    if not code_area:
        return None

    if code_area[0].isspace():
        return None

    token = code_area.split()[0]
    if not token.endswith("."):
        return None

    name = token[:-1]
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


def list_variable_usages(
    etude_path: Path,
    entries: List[Dict[str, str]],
    out_csv: Path,
) -> None:
    lines = etude_path.read_text(encoding="latin-1", errors="ignore").splitlines()

    patterns = build_name_patterns(entries)

    entries_by_name: Dict[str, List[Dict[str, str]]] = {}
    for e in entries:
        name = (e.get("name") or "").upper().strip()
        if not name:
            continue
        entries_by_name.setdefault(name, []).append(e)

    in_procedure = False
    current_paragraph: Optional[str] = None

    occurrences: List[Dict[str, str]] = []

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

        para = detect_paragraph_name(raw)
        if para:
            current_paragraph = para

        line_num = raw[:6].strip()

        for name, pat in patterns.items():
            if not pat.search(code):
                continue

            for e in entries_by_name.get(name, []):
                occ = {
                    "program": e.get("program", ""),
                    "section": e.get("section", ""),
                    "source": e.get("source", ""),
                    "level": e.get("level", ""),
                    "name": name,
                    "full_path": e.get("full_path", ""),
                    "line_etude": line_num,
                    "paragraph": current_paragraph or "",
                    "code_line": code.strip(),
                }
                occurrences.append(occ)

    fieldnames = [
        "program",
        "section",
        "source",
        "level",
        "name",
        "full_path",
        "line_etude",
        "paragraph",
        "code_line",
    ]

    with out_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for occ in occurrences:
            writer.writerow(occ)


def main() -> int:
    args = parse_args()
    etude_path = Path(args.etude_path)
    dict_csv = Path(args.dict_csv)
    out_csv = Path(args.out)

    if not etude_path.exists():
        print(f"[ERREUR] Fichier .etude introuvable : {etude_path}")
        return 1
    if not dict_csv.exists():
        print(f"[ERREUR] Fichier dictionnaire introuvable : {dict_csv}")
        return 1

    entries = load_dictionary(dict_csv)
    if not entries:
        print("[ERREUR] Dictionnaire vide.")
        return 1

    list_variable_usages(etude_path, entries, out_csv)

    print(f"[OK] Liste détaillée des usages de variables générée : {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
