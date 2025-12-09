#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_data_dictionary.py
------------------------

Construit un dictionnaire de données COBOL à partir d'un fichier .etude
(normalisé, avec COPY déjà développées).

Usage :
    python build_data_dictionary.py chemin/vers/programme.etude \
        --out data_dictionary.csv \
        [--ignore chemin/vers/ignore_variables.csv]
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import List, Optional, Tuple

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

    Le fichier doit contenir au minimum les colonnes :
      - scope        : "ALL" ou nom de programme
      - match_type   : "NAME_EXACT", "NAME_PREFIX", ...
      - pattern      : motif à comparer (en majuscules de préférence)
      - comment      : libre, non utilisé par le code

    Si le fichier n'existe pas, retourne une liste vide.
    """
    if csv_path is None or not csv_path.exists():
        return []

    rules: List[dict] = []
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            scope = (row.get("scope") or "ALL").strip().upper()
            match_type = (row.get("match_type") or "NAME_EXACT").strip().upper()
            pattern = (row.get("pattern") or "").strip().upper()
            if not pattern:
                continue
            rules.append(
                {
                    "scope": scope,
                    "match_type": match_type,
                    "pattern": pattern,
                }
            )
    return rules


def should_ignore_entry(entry: dict, rules: List[dict]) -> bool:
    """
    Détermine si une entrée du dictionnaire doit être ignorée
    en fonction des règles chargées.

    V1 : on supporte principalement les match_type suivants :
      - NAME_EXACT  : name == pattern
      - NAME_PREFIX : name commence par pattern

    Le champ 'scope' permet de limiter la règle à un programme :
      - "ALL" : tous les programmes
      - sinon : nom exact de programme (PROGRAM-ID).
    """
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

        # Filtre sur le scope (programme)
        if scope not in ("", "ALL") and scope != program:
            continue

        if match_type == "NAME_EXACT":
            if name == pattern:
                return True
        elif match_type == "NAME_PREFIX":
            if name.startswith(pattern):
                return True
        else:
            # Match types non gérés en V1 → ignorés proprement
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
    """
    Extrait la partie code d'une ligne .etude.

    Hypothèse : colonnes 1–6 = numéro de ligne, colonne 7 = espace ou '*',
    code à partir de la colonne 8.

    On prend donc line[6:].
    """
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
    """
    Met à jour la "source" (MAIN ou nom de COPYBOOK) à partir de lignes
    insérées par expand_copybooks :

        *COPY SRSWFONC
        *END COPYBOOK NAME

    On se veut robuste :
      - n'importe quelle ligne contenant 'END COPYBOOK' (insensible à la casse)
        remet la source à MAIN.
      - n'importe quelle ligne commençant par '*COPY ' fixe la source au nom
        du copybook.
    """
    stripped = code.strip()
    upper = stripped.upper()

    # Fin de COPYBOOK : on revient à MAIN si on voit 'END COPYBOOK' n'importe où
    if "END COPYBOOK" in upper:
        return "MAIN"

    # Début de COPYBOOK : '*COPY NOMCOPY'
    if upper.startswith("*COPY "):
        name = upper[6:].strip()
        if name:
            return name
        return current_source

    return current_source


def parse_data_declaration(code: str) -> Optional[dict]:
    """
    Essaie de parser une déclaration de données COBOL sur une ligne de code.

    Retourne un dict avec :
        level, name, pic, usage, occurs, occurs_depends_on, redefines, value
    ou None si la ligne ne ressemble pas à une déclaration.

    V1 : on ne gère que les cas simples sur une ligne.
         Les continuations dans .etude sont déjà gérées par normalize/expand.
    """
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

    # REDEFINES
    m_red = re.search(r"\bREDEFINES\s+([A-Z0-9\-]+)", rest, re.IGNORECASE)
    if m_red:
        redefines = m_red.group(1).upper()

    # PIC
    m_pic = re.search(r"\bPIC\s+([A-Z0-9\(\)V\+\-\.\,\'\s]+)", rest, re.IGNORECASE)
    if m_pic:
        pic = m_pic.group(1).strip()
        # On coupe à la première occurrence de mot-clé connu après le PIC
        for kw in ["USAGE", "OCCURS", "REDEFINES", "VALUE", "SYNC", "SIGN"]:
            idx = pic.upper().find(" " + kw)
            if idx != -1:
                pic = pic[:idx].strip()
                break

    # USAGE
    m_usage = re.search(r"\bUSAGE\s+([A-Z0-9\-]+)", rest, re.IGNORECASE)
    if m_usage:
        usage = m_usage.group(1).upper()

    # OCCURS / DEPENDING ON
    m_occurs = re.search(
        r"\bOCCURS\s+([0-9]+)(?:\s+TIMES)?(?:\s+DEPENDING\s+ON\s+([A-Z0-9\-]+))?",
        rest,
        re.IGNORECASE,
    )
    if m_occurs:
        occurs = m_occurs.group(1)
        if m_occurs.group(2):
            occurs_depends_on = m_occurs.group(2).upper()

    # VALUE
    m_value = re.search(r"\bVALUE\s+(.+)", rest, re.IGNORECASE)
    if m_value:
        value_raw = m_value.group(1).strip()
        # On coupe à un point final éventuel
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
    """
    Ajoute les champs 'parent_name' et 'full_path' à chaque entrée,
    en se basant sur les niveaux COBOL.

    Règle simple :
      - on maintient une pile (stack) de (level, name, full_path)
      - pour un nouvel élément :
           * on dépile tant que level <= level_stack_top
           * le parent est alors le top de pile restant (level < current)
           * full_path = parent.full_path + "/" + name, ou name seul si pas de parent
      - niveaux 77 et 66 sont considérés comme top-level (pas de parent)
      - niveau 88 (condition-name) : parent = dernier niveau non-88
    """
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

        # Niveau 88 : condition-name
        if lvl == 88:
            # parent = dernier non-88 vu
            if last_non_88 is not None:
                parent_name = last_non_88[1]
                full_path = last_non_88[2] + "/" + name
            else:
                parent_name = ""
                full_path = name
            # on n'ajoute pas les 88 dans la pile hiérarchique
            e["parent_name"] = parent_name
            e["full_path"] = full_path
            continue

        # Niveaux 77 & 66 → indépendants
        if lvl in (66, 77):
            parent_name = ""
            full_path = name
            stack = []  # on considère ces variables comme “en dehors” de la hiérarchie
        else:
            # Gestion de la pile hiérarchique
            while stack and lvl <= stack[-1][0]:
                stack.pop()

            if stack:
                parent_level, parent, parent_path = stack[-1]
                parent_name = parent
                full_path = parent_path + "/" + name
            else:
                parent_name = ""
                full_path = name

            stack.append((lvl, name, full_path))

        last_non_88 = (lvl, name, full_path)

        e["parent_name"] = parent_name
        e["full_path"] = full_path


def build_data_dictionary(
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

        # Mise à jour du contexte global
        current_program = detect_program_id(code, current_program)
        current_section = detect_section(code, current_section)
        current_source = detect_copy_source(code, current_source)

        # On ignore les lignes commentaire (dans la zone code)
        if code.lstrip().startswith("*"):
            continue

        decl = parse_data_declaration(code)
        if not decl:
            continue

        decl["program"] = current_program or ""
        decl["section"] = current_section or ""
        decl["source"] = current_source
        decl["line_etude"] = line[:6].strip()  # numérotation .etude si présente

        entries.append(decl)

    # Chargement des règles d'exclusion
    rules: List[dict] = []
    if ignore_csv is not None:
        rules = load_ignore_rules(ignore_csv)

    # Si aucune règle passée en argument, on tente la détection automatique
    # de params/ignore_variables.csv à côté du script.
    if not rules and ignore_csv is None:
        script_dir = Path(__file__).resolve().parent
        candidate = script_dir / "params" / "ignore_variables.csv"
        rules = load_ignore_rules(candidate)

    # Filtrage des entrées si des règles sont présentes
    if rules:
        entries = [e for e in entries if not should_ignore_entry(e, rules)]

    # Ajout parent_name / full_path
    build_hierarchy(entries)

    # Écriture CSV
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


def main() -> int:
    args = parse_args()
    etude_path = Path(args.etude_path)
    out_csv = Path(args.out)

    ignore_csv: Optional[Path]
    if args.ignore:
        ignore_csv = Path(args.ignore)
    else:
        ignore_csv = None  # auto-détection params/ignore_variables.csv

    if not etude_path.exists():
        print(f"[ERREUR] Fichier .etude introuvable : {etude_path}")
        return 1

    build_data_dictionary(etude_path, out_csv, ignore_csv=ignore_csv)
    print(f"[OK] Dictionnaire de données généré : {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
