# build_program_dd_and_copybooks.py
# V1 — Génération:
# - program_dd.csv (DATA DIVISION only)
# - copybook_dd.csv
# - copybook_ref.csv
# - program_copy_usage.csv
#
# Entrée: work_dir/etude/*.etude
# Sortie: work_dir/data/dd/*.csv
#
# CSV delimiter: ';'

from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set


# ----------------------------
# Regex marqueurs COPYBOOK
# Exemple lignes:
# 000035*END COPYBOOK SRSWFANO
# 000036*COPYBOOK SRSWSRCZ
# ----------------------------
RE_COPY_START = re.compile(r"\*COPYBOOK\s+([A-Z0-9$#@_-]+)", re.IGNORECASE)
RE_COPY_END = re.compile(r"\*END\s+COPYBOOK\s+([A-Z0-9$#@_-]+)", re.IGNORECASE)

# Détection items DATA DIVISION (niveau + nom)
RE_ITEM_START = re.compile(r"^\s*(\d{2})\s+([A-Z0-9$#@_-]+)\b", re.IGNORECASE)

# Sections DATA DIVISION
RE_DATA_DIV = re.compile(r"\bDATA\s+DIVISION\b", re.IGNORECASE)
RE_PROC_DIV = re.compile(r"\bPROCEDURE\s+DIVISION\b", re.IGNORECASE)
RE_SECTION = re.compile(r"\b(FILE\s+SECTION|WORKING-STORAGE\s+SECTION|LOCAL-STORAGE\s+SECTION|LINKAGE\s+SECTION)\b",
                        re.IGNORECASE)

# Clauses (extraction “best effort”)
RE_PIC = re.compile(r"\bPIC(TURE)?\s+(.+?)(?=\s+(USAGE|VALUE|VALUES|REDEFINES|OCCURS|SYNC|SIGN|JUST|BLANK|RENAMES|COMP|BINARY|DISPLAY)\b|\.|$)",
                    re.IGNORECASE)
RE_USAGE = re.compile(r"\b(USAGE\s+IS|USAGE)\s+([A-Z0-9-]+)\b", re.IGNORECASE)
RE_REDEFINES = re.compile(r"\bREDEFINES\s+([A-Z0-9$#@_-]+)\b", re.IGNORECASE)
RE_OCCURS_1 = re.compile(r"\bOCCURS\s+(\d+)\b", re.IGNORECASE)
RE_OCCURS_2 = re.compile(r"\bOCCURS\s+(\d+)\s+TO\s+(\d+)\b", re.IGNORECASE)
RE_DEPENDING = re.compile(r"\bDEPENDING\s+ON\s+([A-Z0-9$#@_-]+)\b", re.IGNORECASE)

# VALUE: on ne remplit que si c’est simple (sinon warning)
RE_VALUE = re.compile(r"\bVALUE\s+(IS\s+)?(.+?)(?=\.|$)", re.IGNORECASE)
RE_VALUES = re.compile(r"\bVALUES\b", re.IGNORECASE)


@dataclass
class ItemRow:
    program: str
    section: str
    level: str
    name: str
    parent_name: str
    full_path: str
    is_group: str
    pic: str
    usage: str
    redefines: str
    occurs_min: str
    occurs_max: str
    depending_on: str
    value: str
    origin_type: str  # LOCAL|COPY
    origin_name: str  # copybook name
    warnings: str


def _code_zone(line: str) -> str:
    """
    COBOL listing-style:
    - colonne 7 = commentaire '*'
    - code zone = colonnes 8–72 (index 7:72)
    Ici on reste pragmatiques: on prend 7:72 si possible, sinon line.
    """
    if len(line) >= 72:
        return line[7:72]
    if len(line) > 7:
        return line[7:]
    return ""


def _is_comment_line(line: str) -> bool:
    # Listing .etude: souvent '*' en colonne 7, ex "000035*END COPYBOOK ..."
    # On détecte le '*' situé tôt dans la ligne (après une zone séquence)
    # et les commentaires "plein".
    if not line:
        return True
    if len(line) >= 7 and line[6] == "*":
        return True
    cz = _code_zone(line).lstrip()
    return cz.startswith("*") or cz.startswith("*>")  # tolérance


def _normalize_token(s: str) -> str:
    return " ".join(s.strip().split())


def _extract_program_name(etude_path: Path) -> str:
    # SRSTC0.cbl.etude -> SRSTC0
    name = etude_path.name
    # enlève doubles extensions
    for suffix in [".etude", ".cbl", ".cob"]:
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
    # parfois: XXX.cbl.etude -> enlever .cbl restant
    if name.lower().endswith(".cbl"):
        name = name[:-4]
    return name


def _join_warnings(existing: List[str], add: Optional[str]) -> None:
    if not add:
        return
    if add not in existing:
        existing.append(add)


def _warnings_str(w: List[str]) -> str:
    return ";".join(w)


def _section_label(raw: str) -> str:
    u = raw.upper()
    if "FILE SECTION" in u:
        return "FILE"
    if "WORKING-STORAGE" in u:
        return "WORKING-STORAGE"
    if "LOCAL-STORAGE" in u:
        return "LOCAL-STORAGE"
    if "LINKAGE" in u:
        return "LINKAGE"
    return ""


def _parse_item_clauses(item_text: str, warnings: List[str]) -> Tuple[str, str, str, str, str, str, str]:
    """
    Retourne: (pic, usage, redefines, occurs_min, occurs_max, depending_on, value)
    """
    txt = " ".join(item_text.split())
    pic = ""
    usage = ""
    redefines = ""
    occurs_min = ""
    occurs_max = ""
    depending_on = ""
    value = ""

    m = RE_PIC.search(txt)
    if m:
        pic = _normalize_token(m.group(2))

    # USAGE (ou COMP/COMP-3 dans le flux)
    m = RE_USAGE.search(txt)
    if m:
        usage = _normalize_token(m.group(2))
    else:
        # fallback: détecter COMP/COMP-3/BINARY/DISPLAY sans "USAGE"
        for u in ["COMP-3", "COMP-2", "COMP-1", "COMP", "BINARY", "DISPLAY", "PACKED-DECIMAL"]:
            if re.search(rf"\b{re.escape(u)}\b", txt, re.IGNORECASE):
                usage = u
                break

    m = RE_REDEFINES.search(txt)
    if m:
        redefines = _normalize_token(m.group(1))

    # OCCURS
    m2 = RE_OCCURS_2.search(txt)
    if m2:
        occurs_min = m2.group(1)
        occurs_max = m2.group(2)
        _join_warnings(warnings, "OCCURS_DEPENDING" if RE_DEPENDING.search(txt) else None)
    else:
        m1 = RE_OCCURS_1.search(txt)
        if m1:
            occurs_min = m1.group(1)
            occurs_max = m1.group(1)
            _join_warnings(warnings, "OCCURS_DEPENDING" if RE_DEPENDING.search(txt) else None)

    m = RE_DEPENDING.search(txt)
    if m:
        depending_on = _normalize_token(m.group(1))

    # VALUE (simple only)
    if RE_VALUES.search(txt):
        # "VALUES ARE" / multiples
        _join_warnings(warnings, "COND_88_MULTI")
    m = RE_VALUE.search(txt)
    if m:
        raw_val = m.group(2).strip()
        # Heuristique: si ça ressemble à multi/complexe, on tag et on laisse vide
        if "\n" in item_text or "  " in raw_val or "THRU" in raw_val.upper() or "THROUGH" in raw_val.upper():
            _join_warnings(warnings, "VALUE_MULTILINE")
        elif len(raw_val) > 80:
            _join_warnings(warnings, "VALUE_COMPLEX")
        else:
            value = _normalize_token(raw_val)

    return pic, usage, redefines, occurs_min, occurs_max, depending_on, value


def generate_dd_and_copybooks(config: dict) -> Dict[str, Path]:
    work_dir = Path(config["work_dir"])
    etude_dir = work_dir / "etude"
    out_dir = work_dir / "data" / "dd"
    out_dir.mkdir(parents=True, exist_ok=True)

    program_dd_path = out_dir / "program_dd.csv"
    copybook_dd_path = out_dir / "copybook_dd.csv"
    copybook_ref_path = out_dir / "copybook_ref.csv"
    program_copy_usage_path = out_dir / "program_copy_usage.csv"

    # Accumulateurs
    program_rows: List[ItemRow] = []
    copybook_rows: List[dict] = []
    copybook_to_programs: Dict[str, Set[str]] = {}
    usage_rows: List[dict] = []

    # Parcours .etude
    etude_files = sorted(etude_dir.glob("*.etude"))
    for etude_path in etude_files:
        program = _extract_program_name(etude_path)

        # États
        in_data = False
        in_proc = False
        current_section = ""
        # Pile hiérarchie DATA
        stack: List[Tuple[int, str, str]] = []  # (level_int, name, full_path)
        last_condition_parent: str = ""          # pour 88
        last_condition_parent_path: str = ""

        # Pile COPYBOOK
        copy_stack: List[dict] = []  # {"name":..., "start_line":..., "nested":bool}
        # pour usage CSV: il faut enregistrer start/end
        copy_usage_open: List[dict] = []

        # Item en cours
        current_item_lines: List[str] = []
        current_item_meta: Optional[Tuple[str, str]] = None  # (level, name)
        current_item_start_line: Optional[int] = None
        current_item_warnings: List[str] = []

        def flush_current_item():
            nonlocal current_item_lines, current_item_meta, current_item_start_line
            nonlocal current_item_warnings, stack, last_condition_parent, last_condition_parent_path

            if not current_item_meta or not current_item_lines:
                current_item_lines = []
                current_item_meta = None
                current_item_start_line = None
                current_item_warnings = []
                return

            level_str, name = current_item_meta
            level_int = int(level_str)
            item_text = "\n".join(current_item_lines)

            # section obligatoire
            sec = current_section

            # Origine
            if copy_stack:
                origin_type = "COPY"
                origin_name = str(copy_stack[-1]["name"])
                if len(copy_stack) > 1:
                    _join_warnings(current_item_warnings, "COPY_NESTED")
            else:
                origin_type = "LOCAL"
                origin_name = ""

            # Hiérarchie (stack)
            parent_name = ""
            parent_path = ""

            if level_int == 88:
                # rattaché au dernier item “parent” rencontré
                parent_name = last_condition_parent
                parent_path = last_condition_parent_path
                full_path = (parent_path + "/" + name) if parent_path else name
            else:
                # pop jusqu’à level inférieur
                while stack and stack[-1][0] >= level_int:
                    stack.pop()
                if stack:
                    parent_name = stack[-1][1]
                    parent_path = stack[-1][2]
                full_path = (parent_path + "/" + name) if parent_path else name

            # Clauses
            pic, usage, redefines, occurs_min, occurs_max, depending_on, value = _parse_item_clauses(item_text, current_item_warnings)
            is_group = "Y" if (pic.strip() == "") and (level_int not in (66, 77, 88)) else "N"
            if level_int == 66:
                _join_warnings(current_item_warnings, "LEVEL_66_RENAMES")
            if redefines:
                _join_warnings(current_item_warnings, "REDEFINES")

            # condition 88 multi / ranges déjà taggué “best effort”
            # VALUE multiline déjà taggué si nécessaire

            # row
            row = ItemRow(
                program=program,
                section=sec,
                level=level_str,
                name=name,
                parent_name=parent_name,
                full_path=full_path,
                is_group=is_group,
                pic=pic,
                usage=usage,
                redefines=redefines,
                occurs_min=occurs_min,
                occurs_max=occurs_max,
                depending_on=depending_on,
                value=value,
                origin_type=origin_type,
                origin_name=origin_name,
                warnings=_warnings_str(current_item_warnings),
            )
            program_rows.append(row)

            # Ajout copybook_dd si origin COPY
            if origin_type == "COPY" and origin_name:
                copybook_rows.append({
                    "copybook_name": origin_name,
                    "section": sec,
                    "level": level_str,
                    "name": name,
                    "parent_name": parent_name,
                    "full_path": full_path,
                    "is_group": is_group,
                    "pic": pic,
                    "usage": usage,
                    "redefines": redefines,
                    "occurs_min": occurs_min,
                    "occurs_max": occurs_max,
                    "depending_on": depending_on,
                    "value": value,
                    "warnings": _warnings_str(current_item_warnings),
                })
                copybook_to_programs.setdefault(origin_name, set()).add(program)

            # Mise à jour stack/parent condition
            if level_int not in (66, 77, 88):
                # 01..49
                stack.append((level_int, name, full_path))
                last_condition_parent = name
                last_condition_parent_path = full_path
            elif level_int == 77:
                # 77: pas vraiment dans la hiérarchie, mais peut servir de parent 88 (rare)
                last_condition_parent = name
                last_condition_parent_path = full_path

            # reset
            current_item_lines = []
            current_item_meta = None
            current_item_start_line = None
            current_item_warnings = []

        # Lecture fichier
        try:
            with open(etude_path, "r", encoding="latin-1", errors="ignore") as f:
                for lineno, raw in enumerate(f, start=1):
                    line = raw.rstrip("\n")

                    # Marqueurs COPYBOOK: on les traite même si ligne commentée
                    m = RE_COPY_START.search(line)
                    if m:
                        copy_name = m.group(1).strip()
                        # ouvrir usage
                        copy_usage_open.append({"program": program, "copybook_name": copy_name, "start_line": lineno})
                        # stack
                        copy_stack.append({"name": copy_name, "start_line": lineno})
                        # ref
                        copybook_to_programs.setdefault(copy_name, set()).add(program)
                        continue

                    m = RE_COPY_END.search(line)
                    if m:
                        copy_name = m.group(1).strip()
                        # fermer usage: chercher dernier open correspondant (en pile)
                        # d'abord: flush item courant si on était en plein parsing
                        flush_current_item()

                        warnings_end: List[str] = []
                        # pile COPY (context)
                        if copy_stack and str(copy_stack[-1]["name"]).upper() == copy_name.upper():
                            copy_stack.pop()
                        else:
                            # mismatch: on tente de retrouver dans la pile
                            idx = None
                            for i in range(len(copy_stack) - 1, -1, -1):
                                if str(copy_stack[i]["name"]).upper() == copy_name.upper():
                                    idx = i
                                    break
                            if idx is not None:
                                # pop jusqu'à l'élément inclus
                                while len(copy_stack) > idx:
                                    copy_stack.pop()
                                _join_warnings(warnings_end, "COPY_END_MISMATCH")
                            else:
                                _join_warnings(warnings_end, "COPY_END_MISMATCH")

                        # fermer usage open correspondant
                        # on prend le dernier open de ce copy_name
                        open_idx = None
                        for i in range(len(copy_usage_open) - 1, -1, -1):
                            if copy_usage_open[i]["copybook_name"].upper() == copy_name.upper():
                                open_idx = i
                                break
                        if open_idx is not None:
                            u = copy_usage_open.pop(open_idx)
                            u["end_line"] = lineno
                            u["warnings"] = _warnings_str(warnings_end)
                            usage_rows.append(u)
                        else:
                            usage_rows.append({
                                "program": program,
                                "copybook_name": copy_name,
                                "start_line": "",
                                "end_line": lineno,
                                "warnings": _warnings_str(warnings_end) or "COPY_END_MISMATCH",
                            })
                        continue

                    # Détection DATA / PROC
                    cz = _code_zone(line)
                    if not in_data and RE_DATA_DIV.search(cz):
                        in_data = True
                        continue
                    if in_data and not in_proc and RE_PROC_DIV.search(cz):
                        # fin parsing DATA
                        flush_current_item()
                        in_proc = True
                        break  # data division only

                    if not in_data or in_proc:
                        continue

                    # section
                    msec = RE_SECTION.search(cz)
                    if msec:
                        flush_current_item()
                        current_section = _section_label(msec.group(1))
                        # reset hiérarchie à chaque section
                        stack = []
                        last_condition_parent = ""
                        last_condition_parent_path = ""
                        continue

                    # ignorer lignes vides / commentaires (hors marqueurs déjà traités)
                    if _is_comment_line(line):
                        continue

                    cz_u = cz.rstrip()

                    # Début d’item ?
                    mitem = RE_ITEM_START.match(cz_u)
                    if mitem:
                        # flush précédent
                        flush_current_item()
                        lvl = mitem.group(1)
                        nam = mitem.group(2)
                        current_item_meta = (lvl, nam)
                        current_item_start_line = lineno
                        current_item_warnings = []
                        current_item_lines = [cz_u.strip()]
                        # si la ligne contient un '.' -> item fini
                        if "." in cz_u:
                            flush_current_item()
                        continue

                    # Continuation d’item
                    if current_item_meta:
                        current_item_lines.append(cz_u.strip())
                        # fin d’item au point
                        if "." in cz_u:
                            flush_current_item()
                        continue

                # fin fichier
                flush_current_item()

        except Exception:
            # si un fichier tombe, on note dans ref? Pour l’instant: on continue.
            continue

        # COPYBOOK usage restants non fermés
        for u in copy_usage_open:
            u["end_line"] = ""
            u["warnings"] = "COPY_END_MISMATCH"
            usage_rows.append(u)

    # Écriture CSV
    def write_csv(path: Path, headers: List[str], rows: List[dict]):
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=headers, delimiter=";")
            w.writeheader()
            for r in rows:
                w.writerow(r)

    # program_dd
    with open(program_dd_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow([
            "program", "section", "level", "name", "parent_name", "full_path",
            "is_group", "pic", "usage", "redefines",
            "occurs_min", "occurs_max", "depending_on",
            "value", "origin_type", "origin_name", "warnings"
        ])
        for r in program_rows:
            w.writerow([
                r.program, r.section, r.level, r.name, r.parent_name, r.full_path,
                r.is_group, r.pic, r.usage, r.redefines,
                r.occurs_min, r.occurs_max, r.depending_on,
                r.value, r.origin_type, r.origin_name, r.warnings
            ])

    # copybook_dd
    write_csv(copybook_dd_path, [
        "copybook_name", "section", "level", "name", "parent_name", "full_path",
        "is_group", "pic", "usage", "redefines",
        "occurs_min", "occurs_max", "depending_on", "value", "warnings"
    ], copybook_rows)

    # copybook_ref
    ref_rows = []
    for cb, progs in sorted(copybook_to_programs.items()):
        ref_rows.append({
            "copybook_name": cb,
            "programs_count": str(len(progs)),
            "programs_list": ";".join(sorted(progs)),
            "warnings": ""
        })
    write_csv(copybook_ref_path, ["copybook_name", "programs_count", "programs_list", "warnings"], ref_rows)

    # program_copy_usage
    write_csv(program_copy_usage_path, ["program", "copybook_name", "start_line", "end_line", "warnings"], usage_rows)

    return {
        "program_dd": program_dd_path,
        "copybook_dd": copybook_dd_path,
        "copybook_ref": copybook_ref_path,
        "program_copy_usage": program_copy_usage_path,
    }
