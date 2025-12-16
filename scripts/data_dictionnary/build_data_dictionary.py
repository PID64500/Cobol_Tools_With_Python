#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_data_dictionary.py
------------------------

Construit un dictionnaire de données COBOL à partir d'un fichier .etude
(normalisé, avec COPY déjà développées).

⚠ Évolution (pipeline)
- Le pipeline appelle build_data_dictionary.build_data_dictionary(...) avec :
    normalized_files, program_structure_csv, global_dd_path, dd_by_program_dir
- La V1 du script ne gérait qu'un seul fichier .etude.
- Ce module supporte désormais les 2 usages :
    1) CLI mono-fichier (historique)
    2) Pipeline multi-fichiers (nouvelle orchestration)
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import List, Optional, Tuple, Iterable


# Regex de base
PROGRAM_ID_RE = re.compile(r"\bPROGRAM-ID\.?\s+([A-Z0-9\-]+)", re.IGNORECASE)
SECTION_RE = re.compile(
    r"\b(WORKING-STORAGE|LINKAGE|FILE|LOCAL-STORAGE)\s+SECTION\.?",
    re.IGNORECASE,
)

# Niveaux COBOL autorisés : 01–49, 66, 77, 88
LEVEL_RE = re.compile(
    r"^\s*(0[1-9]|[1-4][0-9]|66|77|88)\b\s+([A-Z0-9\-]+)", re.IGNORECASE
)


# --------------------------------------------------------------------
#  Gestion des règles d'exclusion (ignore_variables.csv)
# --------------------------------------------------------------------


def load_ignore_rules(csv_path: Path) -> List[dict]:
    """
    Charge un fichier CSV de règles d'exclusion de variables.

    Colonnes attendues :
      - scope        : "ALL" ou nom de programme
      - match_type   : "NAME_EXACT", "NAME_PREFIX", ...
      - pattern      : motif à comparer
    """
    if csv_path is None or not csv_path.exists():
        return []

    for encoding in ("utf-8", "latin-1"):
        try:
            rules: List[dict] = []
            with csv_path.open("r", encoding=encoding, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    scope = (row.get("scope") or "ALL").strip().upper()
                    match_type = (row.get("match_type") or "NAME_EXACT").strip().upper()
                    pattern = (row.get("pattern") or "").strip().upper()
                    if not pattern:
                        continue
                    rules.append(
                        {"scope": scope, "match_type": match_type, "pattern": pattern}
                    )
            return rules
        except UnicodeDecodeError:
            continue

    return []


def should_ignore_entry(entry: dict, rules: List[dict]) -> bool:
    if not rules:
        return False

    program = (entry.get("program") or "").strip().upper()
    name = (entry.get("name") or "").strip().upper()

    for rule in rules:
        scope = rule.get("scope", "ALL")
        match_type = rule.get("match_type", "NAME_EXACT")
        pattern = rule.get("pattern", "")

        if not pattern:
            continue

        if scope not in ("", "ALL") and scope != program:
            continue

        if match_type == "NAME_EXACT":
            if name == pattern:
                return True
        elif match_type == "NAME_PREFIX":
            if name.startswith(pattern):
                return True
        else:
            continue

    return False


# --------------------------------------------------------------------
#  Parsing COBOL
# --------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Construit un dictionnaire de données depuis un .etude COBOL."
    )
    parser.add_argument("etude_path", help="Chemin du fichier .etude en entrée")
    parser.add_argument(
        "--out",
        default="data_dictionary.csv",
        help="Fichier CSV de sortie (défaut : data_dictionary.csv)",
    )
    parser.add_argument(
        "--ignore",
        help="Fichier CSV listant les variables à ignorer (facultatif). "
             "Si non fourni, on cherche params/ignore_variables.csv à côté du script.",
        default=None,
    )
    return parser.parse_args()


def extract_code_part(line: str) -> str:
    if len(line) <= 6:
        return ""
    return line[6:].rstrip("\n")


def detect_program_id(code: str, current_program: Optional[str]) -> Optional[str]:
    m = PROGRAM_ID_RE.search(code)
    if m:
        return m.group(1).upper()
    return current_program


def detect_section(code: str, current_section: Optional[str]) -> Optional[str]:
    m = SECTION_RE.search(code)
    if m:
        return m.group(1).upper() + " SECTION"
    return current_section


def detect_copy_source(code: str, current_source: str) -> str:
    upper = code.upper().strip()

    if upper.startswith("*END COPYBOOK"):
        return "MAIN"

    m = re.match(r"\*COPYBOOK\s+([A-Z0-9\-]+)", upper)
    if m:
        name = m.group(1).strip()
        if name:
            return name

    return current_source


def parse_data_declaration(code: str) -> Optional[dict]:
    m = LEVEL_RE.match(code)
    if not m:
        return None

    level = m.group(1)
    name = m.group(2).upper()

    rest = code[m.end():].strip()

    pic = ""
    usage = ""
    occurs = ""
    occurs_depends_on = ""
    redefines = ""
    value = ""

    m_red = re.search(r"\bREDEFINES\s+([A-Z0-9\-]+)", rest, re.IGNORECASE)
    if m_red:
        redefines = m_red.group(1).upper()

    m_pic = re.search(r"\bPIC\s+([A-Z0-9\(\)V\+\-\.\,\'\s]+)", rest, re.IGNORECASE)
    if m_pic:
        pic = m_pic.group(1).strip()
        for kw in ["USAGE", "OCCURS", "REDEFINES", "VALUE", "SYNC", "SIGN"]:
            idx = pic.upper().find(" " + kw)
            if idx != -1:
                pic = pic[:idx].strip()
                break

    m_usage = re.search(r"\bUSAGE\s+([A-Z0-9\-]+)", rest, re.IGNORECASE)
    if m_usage:
        usage = m_usage.group(1).upper()

    m_occurs = re.search(
        r"\bOCCURS\s+([0-9]+)(?:\s+TIMES)?(?:\s+DEPENDING\s+ON\s+([A-Z0-9\-]+))?",
        rest,
        re.IGNORECASE,
    )
    if m_occurs:
        occurs = m_occurs.group(1)
        if m_occurs.group(2):
            occurs_depends_on = m_occurs.group(2).upper()

    m_value = re.search(r"\bVALUE\s+(.+)", rest, re.IGNORECASE)
    if m_value:
        value_raw = m_value.group(1).strip()
        if "." in value_raw:
            value_raw = value_raw.split(".", 1)[0].strip()
        value = value_raw

    return {
        "level": level,
        "name": name,
        "pic": pic,
        "usage": usage,
        "occurs": occurs,
        "occurs_depends_on": occurs_depends_on,
        "redefines": redefines,
        "value": value,
    }


def build_hierarchy(entries: List[dict]) -> None:
    stack: List[Tuple[int, str, str]] = []
    last_non_88: Optional[Tuple[int, str, str]] = None

    for e in entries:
        lvl_str = e["level"]
        try:
            lvl = int(lvl_str)
        except ValueError:
            lvl = 0

        name = e["name"]
        parent_name = ""
        full_path = name

        if lvl == 88:
            if last_non_88 is not None:
                parent_name = last_non_88[1]
                full_path = last_non_88[2] + "/" + name
            e["parent_name"] = parent_name
            e["full_path"] = full_path
            continue

        if lvl in (66, 77):
            parent_name = ""
            full_path = name
            stack = []
        else:
            while stack and lvl <= stack[-1][0]:
                stack.pop()

            if stack:
                _, parent, parent_path = stack[-1]
                parent_name = parent
                full_path = parent_path + "/" + name

            stack.append((lvl, name, full_path))

        last_non_88 = (lvl, name, full_path)
        e["parent_name"] = parent_name
        e["full_path"] = full_path


# --------------------------------------------------------------------
#  Implémentation mono-fichier (historique)
# --------------------------------------------------------------------


def build_data_dictionary_for_etude(
    etude_path: Path,
    out_csv: Path,
    ignore_csv: Optional[Path] = None,
) -> None:
    """
    Construit le dictionnaire de données pour un .etude donné.
    """
    lines = etude_path.read_text(encoding="latin-1", errors="ignore").splitlines()

    entries: List[dict] = []

    current_program: Optional[str] = None
    current_section: Optional[str] = None
    current_source: str = "MAIN"

    for line in lines:
        code = extract_code_part(line)
        if not code.strip():
            continue

        current_program = detect_program_id(code, current_program)
        current_section = detect_section(code, current_section)
        current_source = detect_copy_source(code, current_source)

        if code.lstrip().startswith("*"):
            continue

        decl = parse_data_declaration(code)
        if not decl:
            continue

        decl["program"] = current_program or ""
        decl["section"] = current_section or ""
        decl["source"] = current_source
        decl["line_etude"] = line[:6].strip()

        entries.append(decl)

    rules: List[dict] = []
    if ignore_csv is not None:
        rules = load_ignore_rules(ignore_csv)

    if not rules and ignore_csv is None:
        script_dir = Path(__file__).resolve().parent
        candidate = script_dir / "params" / "ignore_variables.csv"
        rules = load_ignore_rules(candidate)

    if rules:
        entries = [e for e in entries if not should_ignore_entry(e, rules)]

    build_hierarchy(entries)

    fieldnames = [
        "program",
        "section",
        "source",
        "level",
        "name",
        "parent_name",
        "full_path",
        "pic",
        "usage",
        "occurs",
        "occurs_depends_on",
        "redefines",
        "value",
        "line_etude",
    ]

    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for e in entries:
            writer.writerow(e)


# --------------------------------------------------------------------
#  Orchestration multi-fichiers (attendue par main.py)
# --------------------------------------------------------------------


def _program_name_from_path(etude_path: Path) -> str:
    name = etude_path.name
    for suffix in [".cbl.etude", ".CBL.ETUDE", ".etude", ".ETUDE"]:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return etude_path.stem


def build_data_dictionary(
    normalized_files: Iterable[str],
    program_structure_csv: Path,      # accepté pour compat pipeline (non utilisé ici)
    global_dd_path: Path,
    dd_by_program_dir: Path,
    ignore_csv: Optional[Path] = None,
) -> None:
    """
    API pipeline: génère
      - un dictionnaire par programme dans dd_by_program_dir
      - un dictionnaire global global_dd_path (concat de tous)
    """
    dd_by_program_dir.mkdir(parents=True, exist_ok=True)
    global_dd_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "program",
        "section",
        "source",
        "level",
        "name",
        "parent_name",
        "full_path",
        "pic",
        "usage",
        "occurs",
        "occurs_depends_on",
        "redefines",
        "value",
        "line_etude",
    ]

    # On écrit le global en streaming
    with global_dd_path.open("w", newline="", encoding="utf-8") as f_global:
        w_global = csv.DictWriter(f_global, fieldnames=fieldnames)
        w_global.writeheader()

        for etude_entry in normalized_files:
            etude_path = Path(etude_entry)
            if not etude_path.is_file():
                continue

            program = _program_name_from_path(etude_path)
            out_csv = dd_by_program_dir / f"{program}_dd.csv"

            # Génération per-program
            build_data_dictionary_for_etude(etude_path, out_csv, ignore_csv=ignore_csv)

            # Append dans le global
            with out_csv.open("r", encoding="utf-8", newline="") as f_in:
                reader = csv.DictReader(f_in)
                for row in reader:
                    w_global.writerow(row)


# --------------------------------------------------------------------
#  CLI
# --------------------------------------------------------------------


def main() -> int:
    args = parse_args()
    etude_path = Path(args.etude_path)
    out_csv = Path(args.out)

    ignore_csv: Optional[Path]
    if args.ignore:
        ignore_csv = Path(args.ignore)
    else:
        ignore_csv = None

    if not etude_path.exists():
        print(f"[ERREUR] Fichier .etude introuvable : {etude_path}")
        return 1

    build_data_dictionary_for_etude(etude_path, out_csv, ignore_csv=ignore_csv)
    print(f"[OK] Dictionnaire de données généré : {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
