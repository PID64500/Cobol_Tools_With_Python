#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
list_sources.py
----------------
Responsabilite :
- Lire config.yaml
- Lister les fichiers COBOL à traiter
- Creer un log list_sources.log dans output_dir

Le log contient :
  - Les fichiers COBOL detectés
  - Le nom des fichiers .etude qui seront generes
"""

import os
import yaml
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)


def load_config(config_path: str = "config.yaml") -> Dict:
    """Charge la configuration YAML."""
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration introuvable : {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def list_cobol_sources(config: Dict) -> List[str]:
    """Retourne la liste des sources COBOL."""
    source_dir = config.get("source_dir", "./sources")
    exts = config.get("source_extensions", [".cbl"])
    recurse = bool(config.get("recurse", True))

    source_dir = os.path.abspath(source_dir)

    if not os.path.isdir(source_dir):
        raise NotADirectoryError(f"Repertoire source introuvable : {source_dir}")

    cobol_files: List[str] = []

    if recurse:
        for root, dirs, files in os.walk(source_dir):
            for name in files:
                if _has_extension(name, exts):
                    cobol_files.append(os.path.abspath(os.path.join(root, name)))
    else:
        for name in os.listdir(source_dir):
            full = os.path.join(source_dir, name)
            if os.path.isfile(full) and _has_extension(name, exts):
                cobol_files.append(os.path.abspath(full))

    # Création du log des sources COBOL
    write_sources_log(config, cobol_files)

    return cobol_files


def _has_extension(filename: str, extensions: List[str]) -> bool:
    """True si filename se termine par une extension COBOL."""
    for ext in extensions:
        if filename.endswith(ext):
            return True
    return False


def write_sources_log(config: Dict, cobol_files: List[str]) -> None:
    """
    Crée list_sources.log dans output_dir :
    - liste des COBOL trouvés
    - liste des .etude correspondants
    """
    output_dir = os.path.abspath(config.get("output_dir", "./output"))
    work_dir = os.path.abspath(config.get("work_dir", "./work"))

    os.makedirs(output_dir, exist_ok=True)

    log_path = os.path.join(output_dir, "list_sources.log")

    with open(log_path, "w", encoding="utf-8") as f:

        f.write("=== Liste des fichiers COBOL detectes ===\n\n")

        if cobol_files:
            for path in cobol_files:
                f.write(f"COBOL : {path}\n")
        else:
            f.write("(Aucun fichier COBOL detecte)\n")

        f.write("\n=== Fichiers .etude qui seront generes ===\n\n")

        if cobol_files:
            for path in cobol_files:
                base = os.path.basename(path)
                etude = os.path.join(work_dir, base + ".etude")
                f.write(f"ETUDE : {etude}\n")
        else:
            f.write("(Aucun fichier .etude)\n")

    print(f"[OK] Log des sources ecrit dans : {log_path}")


# Mode autonome
if __name__ == "__main__":
    cfg = load_config("config.yaml")
    files = list_cobol_sources(cfg)

    print("# Fichiers COBOL detectes :")
    for path in files:
        print(" ", path)
    print(f"\nTotal : {len(files)} fichier(s).")
