#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scan_variable_usage.py
----------------------

À partir :
  - d'un fichier .etude COBOL
  - d'un CSV dictionnaire produit par build_data_dictionary.py

Produit :
  - un CSV indiquant, pour chaque variable, si elle est utilisée
    dans la PROCEDURE DIVISION du programme.

Usage :
  python scan_variable_usage.py prog.etude prog_dd.csv --out prog_usage.csv
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Dict, List, Optional


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyse l'utilisation des variables à partir du dictionnaire et de la PROCEDURE DIVISION."
    )
    parser.add_argument("etude_path", help="Chemin du fichier .etude")
    parser.add_argument("dict_csv", help="CSV du dictionnaire (build_data_dictionary.py)")
    parser.add_argument(
        "--out",
        default="variables_usage.csv",
        help="CSV de sortie (défaut : variables_usage.csv)",
    )
    return parser.parse_args()


def extract_code_part(line: str) -> str:
    """
    Même logique que build_data_dictionary :
    colonnes 1–6 = numéros, col.7 = espace ou '*', code à partir de col.8.
    """
    if len(line) <= 6:
        return ""
    return line[6:].rstrip("\n")


def load_dictionary(dict_csv: Path) -> List[Dict[str, str]]:
    """
    Charge le CSV du dictionnaire en mémoire.

    On garde les colonnes importantes :
      program, section, source, level, name, parent_name, full_path, ...
    """
    entries: List[Dict[str, str]] = []
    with dict_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            entries.append(row)
    return entries


def build_name_patterns(entries: List[Dict[str, str]]) -> Dict[str, re.Pattern]:
    """
    Construit un regex par nom de variable pour éviter les faux positifs.

    On veut matcher NAME comme un identifiant COBOL isolé :
      - pas de lettre/chiffre/dash avant
      - pas de lettre/chiffre/dash après

    Pattern : (?<![A-Z0-9-])NAME(?![A-Z0-9-])
    """
    patterns: Dict[str, re.Pattern] = {}
    for e in entries:
        name = (e.get("name") or "").upper().strip()
        if not name:
            continue
        if name in patterns:
            continue
        # On compile en insensible à la casse
        pat = re.compile(r"(?<![A-Z0-9-])" + re.escape(name) + r"(?![A-Z0-9-])", re.IGNORECASE)
        patterns[name] = pat
    return patterns


def scan_procedure_usage(etude_path: Path, entries: List[Dict[str, str]]) -> None:
    """
    Met à jour les entrées du dictionnaire avec des infos d'utilisation :

      used_direct : Y/N (vue textuellement dans la PROCEDURE DIVISION)
      used        : Y/N (utilisée directement OU via un enfant)
      usage_count : nombre d'occurrences
      first_usage_line : première ligne .etude où vue
    """
    # Préparation des structures
    patterns = build_name_patterns(entries)

    # Initialisation des compteurs
    for e in entries:
        e["used_direct"] = "N"
        e["used"] = "N"
        e["usage_count"] = "0"
        e["first_usage_line"] = ""

    # On charge tout le fichier .etude
    lines = etude_path.read_text(encoding="latin-1", errors="ignore").splitlines()

    in_procedure = False

    # Pour accélérer, on regroupe les entries par name
    entries_by_name: Dict[str, List[Dict[str, str]]] = {}
    for e in entries:
        name = (e.get("name") or "").upper().strip()
        if not name:
            continue
        entries_by_name.setdefault(name, []).append(e)

    for raw in lines:
        code = extract_code_part(raw)
        if not code.strip():
            continue

        uc = code.upper()

        # Détection du début de PROCEDURE DIVISION
        if not in_procedure and "PROCEDURE DIVISION" in uc:
            in_procedure = True
            # On continue quand même, au cas où des variables sont utilisées
            # sur la même ligne (rare mais possible)
            # -> pas de 'continue' ici

        if not in_procedure:
            continue

        # Ignore commentaires dans la zone code (* en col.7 ou en début de zone code)
        if code.lstrip().startswith("*"):
            continue

        # Ligne .etude pour info (colonnes 1–6)
        line_num = raw[:6].strip()

        # On teste chaque nom de variable avec son regex
        for name, pat in patterns.items():
            if pat.search(code):
                # Variable "name" vue sur cette ligne
                for e in entries_by_name.get(name, []):
                    # On peut filtrer par section si un jour on veut exclure FILE SECTION, etc.
                    count = int(e["usage_count"])
                    count += 1
                    e["usage_count"] = str(count)
                    if e["used_direct"] != "Y":
                        e["used_direct"] = "Y"
                        e["first_usage_line"] = line_num or e["first_usage_line"]

    # Propagation de l'utilisation aux groupes (parents)
    # On utilise full_path si présent, sinon juste name.
    entries_by_full_path: Dict[str, Dict[str, str]] = {}
    for e in entries:
        fp = e.get("full_path") or ""
        if fp:
            entries_by_full_path[fp] = e

    # On commence par marquer used = used_direct, puis on propage
    for e in entries:
        if e["used_direct"] == "Y":
            e["used"] = "Y"

    # Propagation : si A/B/C est utilisé, alors A/B et A sont considérés comme utilisés
    # si on les trouve dans le dictionnaire.
    for e in entries:
        if e["used_direct"] != "Y":
            continue
        fp = e.get("full_path") or ""
        if not fp:
            continue
        parts = fp.split("/")
        # On enlève le dernier (lui-même) et on remonte
        while len(parts) > 1:
            parts = parts[:-1]
            parent_fp = "/".join(parts)
            parent = entries_by_full_path.get(parent_fp)
            if not parent:
                continue
            if parent["used"] != "Y":
                parent["used"] = "Y"
                # On ne touche pas usage_count / first_usage_line pour les parents
                # (option : on pourrait y mettre un flag "used_as_parent")
    # Les variables sans aucune utilisation restent used = "N"


def write_usage_csv(entries: List[Dict[str, str]], out_csv: Path) -> None:
    """
    Écrit le CSV de sortie avec les infos d'utilisation.
    On reprend les colonnes du dictionnaire + 4 colonnes d'usage.
    """
    if not entries:
        print(f"[AVERTISSEMENT] Aucun enregistrement dans le dictionnaire, rien à écrire.")
        return

    # On prend les colonnes existantes du premier enregistrement
    base_fields = list(entries[0].keys())

    # Mais on veut s'assurer de l'ordre des colonnes importantes
    # (si elles existent)
    preferred_order = [
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
        "used_direct",
        "used",
        "usage_count",
        "first_usage_line",
    ]

    # Construire la liste finale de colonnes
    seen = set()
    fieldnames: List[str] = []
    for col in preferred_order:
        if col in base_fields and col not in seen:
            fieldnames.append(col)
            seen.add(col)
    for col in base_fields:
        if col not in seen:
            fieldnames.append(col)
            seen.add(col)

    with out_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for e in entries:
            writer.writerow(e)


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

    scan_procedure_usage(etude_path, entries)
    write_usage_csv(entries, out_csv)

    print(f"[OK] Analyse d'utilisation des variables générée : {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
