#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
main.py — Etape 2
-----------------
Actuellement :
  1) Charge config.yaml
  2) Vide work_dir et output_dir
  3) Normalise tous les fichiers COBOL de source_dir vers work_dir
"""

import sys
import os
import yaml

from clean_dirs import clean_work_and_output
from list_sources import load_config, list_cobol_sources
from normalize_file import normalize_file


def main():
    cfg_file = "config.yaml"
    if len(sys.argv) >= 2:
        cfg_file = sys.argv[1]

    # 1) Charger la configuration
    config = load_config(cfg_file)

    print("\n=== Etape 1 : Vidage des repertoires ===\n")
    clean_work_and_output(config)

    # 2) Recuperer les chemins importants
    work_dir = os.path.abspath(config.get("work_dir", "./work"))
    input_encoding = config.get("input_encoding", "latin-1")
    output_encoding = config.get("output_encoding", "latin-1")

    # 3) Lister les sources COBOL
    print("\n=== Etape 2 : Normalisation des sources COBOL ===\n")
    cobol_files = list_cobol_sources(config)

    if not cobol_files:
        print("Aucun fichier COBOL trouve dans source_dir.")
        return

    for src in cobol_files:
        normalize_file(
            input_file=src,
            work_dir=work_dir,
            input_encoding=input_encoding,
            output_encoding=output_encoding,
        )

    print("\n=== Normalisation terminee ===\n")


if __name__ == "__main__":
    main()
