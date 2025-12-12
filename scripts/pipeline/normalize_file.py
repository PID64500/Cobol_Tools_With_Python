#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
normalize_file.py
-----------------
Étape 2 : normalisation d'un source COBOL pour analyse.

Pipeline pour un fichier COBOL :
  1) Lecture du source brut
  2) Expansion des COPY (avec REPLACING) via copy_expander.expand_copybooks
  3) Filtrage des lignes inutiles :
       - lignes SMASH de debugger (texte commençant par 'SMASH' après trim à gauche)
       - commentaires (col 7 = '*') SAUF les sentinelles *COPYBOOK / *END COPYBOOK
       - lignes JCL commençant par '//'
       - lignes vides en zone code (col 8-72)
  4) Renumérotation des lignes (col 1-6) à partir de seq_start
  5) Écriture du .cbl.etude dans <work_dir>/etude
"""

import os
from typing import List, Dict, Optional
import logging

from copy_expander import expand_copybooks

logger = logging.getLogger(__name__)


def normalize_file(
    input_file: str,
    work_dir: str,
    input_encoding: str = "latin-1",
    output_encoding: str = "latin-1",
    seq_start: int = 1,
    copybooks_dir: Optional[str] = None,
) -> Optional[str]:
    """
    Normalise un source COBOL et écrit le .etude dans work_dir.

    Règles importantes :
      - expansion des COPY avant filtrage
      - toute ligne dont le texte (après strip à gauche) commence par 'SMASH'
        est ignorée (lignes de debugger), y compris si elles viennent d'un COPY.
    """
    os.makedirs(work_dir, exist_ok=True)

    base_name = os.path.basename(input_file)
    output_file = os.path.join(work_dir, base_name + ".etude")

    # 1) Lecture du source brut
    try:
        with open(input_file, "r", encoding=input_encoding, errors="ignore") as fin:
            lines = fin.readlines()
    except Exception as e:
        print(f"[ERREUR] Lecture {input_file} : {e}")
        return None

    # 2) Expansion des COPY (avec REPLACING)
    try:
        lines = expand_copybooks(lines, copybooks_dir)
    except Exception as e:
        msg = f"[WARNING] Échec du développement des COPY pour {input_file} : {e}"
        print(msg)
        logger.warning(msg)

    out_lines: List[str] = []
    seq = seq_start

    # 3) Filtrage + renumérotation
    for raw in lines:
        # On enlève seulement le \n de fin
        raw_line = raw.rstrip("\n")

        # 🔹 Filtre global SMASH (avant tout, sur le texte brut après trim à gauche)
        if raw_line.lstrip().startswith("SMASH"):
            continue

        # On travaille sur 80 colonnes fixes
        line = raw_line
        if len(line) < 80:
            line = line.ljust(80)
        else:
            line = line[:80]

        # JCL éventuel : lignes commençant par //
        if line.startswith("//"):
            continue

        # Gestion des commentaires / sentinelles
        # Colonne 7 => index 6
        indicator = line[6] if len(line) > 6 else " "

        is_sent = False
        if indicator == "*":
            # zone col 7-72 pour tester *COPYBOOK / *END COPYBOOK
            code_with_star = line[6:72]  # col 7-72 (inclut '*')
            stripped = code_with_star.strip().upper()
            if stripped.startswith("*COPYBOOK ") or stripped.startswith("*END COPYBOOK"):
                is_sent = True

        if indicator == "*" and not is_sent:
            # vrai commentaire à ignorer
            continue

        # Zone code : colonnes 8-72
        code_area = line[7:72].strip()
        if code_area == "":
            # ligne vide en zone code
            continue

        # Colonnes 1-6 : nouveau numéro de séquence
        seq_str = f"{seq:06d}"

        # Colonnes 7-72 : on garde l'existant
        middle = line[6:72]   # index 6 = col7, index 71 = col72

        # Colonnes 73-80 : espaces
        new_line = seq_str + middle + " " * 8 + "\n"

        out_lines.append(new_line)
        seq += 1

        if seq > 999999:
            print(f"[WARN] {input_file} : plus de 999999 lignes, arrêt.")
            break

    # 4) Écriture du .etude
    try:
        with open(output_file, "w", encoding=output_encoding, errors="ignore") as fout:
            fout.writelines(out_lines)
        print(f"[OK] Normalisé : {output_file}")
        return output_file
    except Exception as e:
        print(f"[ERREUR] Écriture {output_file} : {e}")
        return None


def normalize_list_files(source_files: List[str], config: Dict) -> List[str]:
    """
    Normalise une liste de fichiers COBOL "bruts" en fichiers .etude.

    Utilise les clés suivantes de config.yaml :
      - work_dir
      - input_encoding
      - output_encoding
      - sequence_start
      - copybooks.dir (si copybooks.enabled = true)
    """
    work_root = config.get("work_dir", "./work")
    etude_dir = os.path.join(work_root, "etude")
    input_encoding = config.get("input_encoding", "latin-1")
    output_encoding = config.get("output_encoding", "utf-8")
    seq_start = int(config.get("sequence_start", 1))

    copybooks_cfg = config.get("copybooks", {})
    copybooks_enabled = copybooks_cfg.get("enabled", True)
    copybooks_dir = copybooks_cfg.get("dir") if copybooks_enabled else None

    normalized_paths: List[str] = []

    for src in source_files:
        etude_path = normalize_file(
            input_file=src,
            work_dir=etude_dir,
            input_encoding=input_encoding,
            output_encoding=output_encoding,
            seq_start=seq_start,
            copybooks_dir=copybooks_dir,
        )
        if etude_path is not None:
            normalized_paths.append(etude_path)

    return normalized_paths


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        print("Usage : python normalize_file.py <source.cbl> <work_dir>")
        sys.exit(1)

    normalize_file(sys.argv[1], sys.argv[2])
