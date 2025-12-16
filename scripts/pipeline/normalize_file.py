#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
normalize_file.py
-----------------
Étape 2 : normalisation d'un source COBOL pour analyse.

Objectif (contrat) :
- Produire des fichiers .etude dans <work_dir>/etude
- Renumérotation des lignes (col 1-6) à partir de seq_start
- Conservation de la zone 7-72
- Filtrage : SMASH, JCL //, commentaires col7='*' (sauf sentinelles COPYBOOK)
- Expansion des COPYBOOK si copybooks_dir est fourni (avec sentinelles *COPYBOOK / *END COPYBOOK)

Pipeline pour un fichier COBOL :
  1) Lecture du source brut
  2) Expansion COPYBOOK (optionnelle)
  3) Filtrage
  4) Renumérotation
  5) Écriture .etude
"""

import os
import logging
from typing import List, Dict, Optional

from .copy_expander import expand_copybooks

logger = logging.getLogger(__name__)


def _is_copy_sentinel(line80: str) -> bool:
    """
    Retourne True si la ligne (80 colonnes) est une sentinelle COPYBOOK :
    - *COPYBOOK XXX
    - *END COPYBOOK XXX

    Hypothèse .etude : col 7 = '*' (index 6).
    On teste sur col 7-72 (index 6:72) en trim + upper.
    """
    if len(line80) < 7:
        return False
    if line80[6] != "*":
        return False

    chunk = line80[6:72].strip().upper()
    return chunk.startswith("*COPYBOOK ") or chunk.startswith("*END COPYBOOK")


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

    Règles :
      - toute ligne dont le texte (après strip à gauche) commence par 'SMASH' est ignorée
      - commentaires (col 7 = '*') ignorés SAUF sentinelles *COPYBOOK / *END COPYBOOK
      - si copybooks_dir est fourni : expansion des COPY via expand_copybooks(...)
    """
    os.makedirs(work_dir, exist_ok=True)

    base_name = os.path.basename(input_file)
    output_file = os.path.join(work_dir, base_name + ".etude")

    # 1) Lecture du source brut
    try:
        with open(input_file, "r", encoding=input_encoding, errors="ignore") as fin:
            lines = fin.readlines()
    except Exception as e:
        logger.error("❌ Lecture %s : %s", input_file, e)
        return None

    # 2) Expansion COPYBOOK si configurée
    if copybooks_dir:
        # Fail-fast : si copybooks_dir est fourni, on produit un .etude EXPANDÉ
        lines = expand_copybooks(lines, copybooks_dir, encoding=input_encoding)
        logger.info("✅ Expansion COPY activée : %s (dir=%s)", input_file, copybooks_dir)
    else:
        logger.info("ℹ️ Expansion COPY désactivée (copybooks_dir non fourni) : %s", input_file)

    out_lines: List[str] = []
    seq = seq_start

    # 3) Filtrage + renumérotation
    for raw in lines:
        raw_line = raw.rstrip("\n")

        # Filtre global SMASH
        if raw_line.lstrip().startswith("SMASH"):
            continue

        # On force 80 colonnes
        line = raw_line
        if len(line) < 80:
            line = line.ljust(80)
        else:
            line = line[:80]

        # JCL éventuel : lignes commençant par //
        if line.startswith("//"):
            continue

        # Gestion des commentaires / sentinelles
        indicator = line[6] if len(line) > 6 else " "
        is_sent = _is_copy_sentinel(line)

        if indicator == "*" and not is_sent:
            # vrai commentaire à ignorer
            continue

        # Zone code : colonnes 8-72
        code_area = line[7:72].strip()
        if code_area == "":
            continue

        # Renumérotation col 1-6
        seq_str = f"{seq:06d}"

        # Col 7-72 conservées
        middle = line[6:72]

        # Col 73-80 : espaces
        new_line = seq_str + middle + " " * 8 + "\n"
        out_lines.append(new_line)

        seq += 1
        if seq > 999999:
            logger.warning("[WARN] %s : plus de 999999 lignes, arrêt.", input_file)
            break

    # 4) Écriture .etude
    try:
        with open(output_file, "w", encoding=output_encoding, errors="ignore") as fout:
            fout.writelines(out_lines)
        logger.info("✅ Normalisé : %s", output_file)
        return output_file
    except Exception as e:
        logger.error("❌ Écriture %s : %s", output_file, e)
        return None


def normalize_list_files(source_files: List[str], config: Dict) -> List[str]:
    """
    Normalise une liste de fichiers COBOL "bruts" en fichiers .etude.

    Clés config.yaml utilisées :
      - work_dir
      - input_encoding
      - output_encoding
      - sequence_start
      - copybooks.enabled
      - copybooks.dir
    """
    work_root = config.get("work_dir", "./work")
    etude_dir = os.path.join(work_root, "etude")

    input_encoding = config.get("input_encoding", "latin-1")
    output_encoding = config.get("output_encoding", "utf-8")
    seq_start = int(config.get("sequence_start", 1))

    copybooks_cfg = config.get("copybooks", {}) or {}
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
