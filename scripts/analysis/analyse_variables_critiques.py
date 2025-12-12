#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyse_variables_critiques.py
------------------------------

À partir :
  - d'un fichier .etude COBOL
  - d'un CSV d'usage des variables (sortie de scan_variable_usage.py)

Produit :
  - un CSV listant toutes les variables avec des indicateurs :
    * nb_paragraphs
    * nb_reads
    * nb_writes
    * nb_conditions
    * nb_io
    * has_88 / nb_88
    * usage_count (global)
    * is_critical (Y/N)
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Set


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyse les variables 'métier critiques' d'un programme COBOL."
    )
    parser.add_argument("etude_path", help="Chemin du fichier .etude")
    parser.add_argument("usage_csv", help="CSV d'usage (sortie de scan_variable_usage.py)")
    parser.add_argument(
        "--out",
        default="variables_critiques.csv",
        help="CSV de sortie (défaut : variables_critiques.csv)",
    )
    return parser.parse_args()


def extract_code_part(line: str) -> str:
    """
    colonnes 1–6 = numéros, col.7 = espace ou '*', code à partir de col.8.
    """
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


def compute_88_for_parents(entries: List[Dict[str, str]]) -> Dict[Tuple[str, str, str, str], int]:
    counts: Dict[Tuple[str, str, str, str], int] = {}

    for e in entries:
        level = (e.get("level") or "").strip()
        if level != "88":
            continue

        program = (e.get("program") or "").upper()
        section = (e.get("section") or "").upper()
        fp_88 = (e.get("full_path") or "").upper()
        if not fp_88 or "/" not in fp_88:
            parent_name = (e.get("parent_name") or "").upper()
            if not parent_name:
                continue
            key = (program, section, parent_name, parent_name)
            counts[key] = counts.get(key, 0) + 1
            continue

        parent_fp = fp_88.rsplit("/", 1)[0]
        parent_name = parent_fp.split("/")[-1]
        key = (program, section, parent_name, parent_fp)
        counts[key] = counts.get(key, 0) + 1

    return counts


def analyse_usages_detailles(
    etude_path: Path,
    entries: List[Dict[str, str]],
) -> Dict[Tuple[str, str, str, str], Dict[str, object]]:
    patterns = build_name_patterns(entries)

    entries_by_name: Dict[str, List[Dict[str, str]]] = {}
    for e in entries:
        name = (e.get("name") or "").upper().strip()
        if not name:
            continue
        entries_by_name.setdefault(name, []).append(e)

    stats: Dict[Tuple[str, str, str, str], Dict[str, object]] = {}

    def get_stats_key(entry: Dict[str, str]) -> Tuple[str, str, str, str]:
        program = (entry.get("program") or "").upper()
        section = (entry.get("section") or "").upper()
        name = (entry.get("name") or "").upper()
        fp = (entry.get("full_path") or "").upper() or name
        return (program, section, name, fp)

    for e in entries:
        level = (e.get("level") or "").strip()
        if level == "88":
            continue

        key = get_stats_key(e)
        if key not in stats:
            stats[key] = {
                "nb_paragraphs": set(),  # type: Set[str]
                "nb_reads": 0,
                "nb_writes": 0,
                "nb_conditions": 0,
                "nb_io": 0,
            }

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
                    level = (e.get("level") or "").strip()
                    if level == "88":
                        continue

                    key = get_stats_key(e)
                    if key not in stats:
                        continue
                    st = stats[key]

                    if current_paragraph:
                        st["nb_paragraphs"].add(current_paragraph)

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

    for st in stats.values():
        st["nb_paragraphs"] = len(st["nb_paragraphs"])

    return stats


def infer_role(name: str, root_name: str, pic: str) -> str:
    u = name.upper()
    r = root_name.upper()
    pic_u = (pic or "").upper()

    if "FLAG" in u or "FLAG" in r or "IND" in u or "INDIC" in u or "ETAT" in u or "STATE" in u:
        return "FLAG/ETAT"

    if "CODE" in u or "CD-" in u:
        return "CODE"

    if "ID" in u or u.endswith("-ID") or "IDENT" in u:
        return "IDENTIFIANT"

    if "DATE" in u or "DT-" in u:
        return "DATE"

    if "MONTANT" in u or "AMT" in u or "AMOUNT" in u:
        return "MONTANT"

    if pic_u.startswith("S9") or pic_u.startswith("9("):
        return "NUMERIQUE"

    return ""


def build_variables_critiques(
    etude_path: Path,
    usage_rows: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    detailed_stats = analyse_usages_detailles(etude_path, usage_rows)
    counts_88 = compute_88_for_parents(usage_rows)

    results: List[Dict[str, str]] = []

    for e in usage_rows:
        level = (e.get("level") or "").strip()
        if level == "88":
            continue

        program = (e.get("program") or "")
        section = (e.get("section") or "")
        source = (e.get("source") or "")
        name = (e.get("name") or "")
        fp = e.get("full_path") or name
        pic = e.get("pic") or ""
        usage_flag = (e.get("used") or "N")
        usage_count = e.get("usage_count") or "0"

        key = (
            (program or "").upper(),
            (section or "").upper(),
            (name or "").upper(),
            (fp or "").upper(),
        )

        st = detailed_stats.get(key, None)
        nb_paragraphs = st["nb_paragraphs"] if st else 0
        nb_reads = st["nb_reads"] if st else 0
        nb_writes = st["nb_writes"] if st else 0
        nb_conditions = st["nb_conditions"] if st else 0
        nb_io = st["nb_io"] if st else 0

        nb_88 = counts_88.get(key, 0)
        has_88 = "Y" if nb_88 > 0 else "N"

        root_name = fp.split("/")[0] if "/" in fp else fp

        try:
            usage_count_int = int(usage_count)
        except ValueError:
            usage_count_int = 0

        is_critical = (
            nb_conditions > 0
            or nb_io > 0
            or nb_paragraphs >= 2
            or has_88 == "Y"
            or usage_count_int > 5
        )
        is_critical_flag = "Y" if is_critical else "N"

        role = infer_role(name, root_name, pic)

        result = {
            "program": program,
            "section": section,
            "source": source,
            "root_name": root_name,
            "name": name,
            "full_path": fp,
            "level": level,
            "pic": pic,
            "usage_flag": usage_flag,
            "usage_count": usage_count,
            "nb_paragraphs": str(nb_paragraphs),
            "nb_reads": str(nb_reads),
            "nb_writes": str(nb_writes),
            "nb_conditions": str(nb_conditions),
            "nb_io": str(nb_io),
            "has_88": has_88,
            "nb_88": str(nb_88),
            "is_critical": is_critical_flag,
            "role_infered": role,
        }

        results.append(result)

    return results


def write_variables_critiques(rows: List[Dict[str, str]], out_csv: Path) -> None:
    if not rows:
        print("[AVERTISSEMENT] Aucune variable trouvée.")
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
        "usage_flag",
        "usage_count",
        "nb_paragraphs",
        "nb_reads",
        "nb_writes",
        "nb_conditions",
        "nb_io",
        "has_88",
        "nb_88",
        "is_critical",
        "role_infered",
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

    rows = build_variables_critiques(etude_path, usage_rows)
    write_variables_critiques(rows, out_csv_path)

    print(f"[OK] Variables critiques générées dans : {out_csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
