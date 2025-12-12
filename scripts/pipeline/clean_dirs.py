#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
clean_dirs.py
-------------
Vide les repertoires work_dir et output_dir definis dans config.yaml.

- Cree les repertoires s'ils n'existent pas.
- Supprime tout le contenu (fichiers + sous-dossiers).
- Affiche ce qu'il supprime.
- Ecrit un fichier de log clean_dirs.log dans output_dir
  listant tout ce qui a ete supprime.
- Recrée l'ossature standard dans work_dir et output_dir.
"""

import os
import shutil
import logging
import yaml
from datetime import datetime

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------
# Sous-structures standard
# --------------------------------------------------------------------

WORK_SUBDIRS = [
    "etude",
    "paragraphs",
    os.path.join("data", "dd"),
    os.path.join("data", "usage"),
    os.path.join("data", "unused"),
    "cics",
    "structure",
    "tmp",
]

OUTPUT_SUBDIRS = [
    "reports",
    "graphs",
    "consolidated",
    "log_export",
]


# --------------------------------------------------------------------
# Utilitaires
# --------------------------------------------------------------------

def ensure_dir(path: str) -> None:
    """Cree le repertoire s'il n'existe pas."""
    os.makedirs(path, exist_ok=True)


def clean_dir(path: str, log_entries: list[str], label: str) -> None:
    """
    Supprime tout le contenu d'un repertoire (fichiers + sous-dossiers),
    mais laisse le repertoire lui-meme.
    """
    logger.info("def clean_dir " + path + " " + label)
    ensure_dir(path)
    log_entries.append(f"[INFO] Nettoyage du repertoire {label} : {path}")
    
    for entry in os.listdir(path):
        full_path = os.path.join(path, entry)
        
        try:
            if os.path.isfile(full_path) or os.path.islink(full_path):
                os.remove(full_path)
                log_entries.append(f"[DEL FILE] {full_path}")
            elif os.path.isdir(full_path):
                shutil.rmtree(full_path)
                log_entries.append(f"[DEL DIR ] {full_path}")
        except Exception as e:
            msg = f"[WARN] Impossible de supprimer {full_path} : {e}"
            print(msg)
            log_entries.append(msg)


def ensure_subdirs(base: str, subdirs: list[str], log_entries: list[str], label: str) -> None:
    """
    Cree les sous-repertoires standards dans base.
    """
    for sub in subdirs:
        path = os.path.join(base, sub)
        ensure_dir(path)
        log_entries.append(f"[MKDIR] {label} subdir : {path}")


# --------------------------------------------------------------------
# Coeur
# --------------------------------------------------------------------

def load_config(config_path: str) -> dict:
    """Charge config.yaml"""
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"config.yaml introuvable : {config_path}")

    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    return cfg


def clean_work_and_output(config_or_path) -> None:
    """
    Nettoie work_dir et output_dir.

    - Si on reçoit un dict (cas main.py) : on l'utilise directement.
    - Si on reçoit une string : on la considère comme chemin vers config.yaml.
    """
    # 1) Récupérer la config
    if isinstance(config_or_path, dict):
        config = config_or_path
    else:
        # on suppose que c'est un chemin de fichier
        config = load_config(config_or_path)

    work_dir = config.get("work_dir")
    output_dir = config.get("output_dir")

    if not work_dir or not output_dir:
        raise ValueError("Les clefs 'work_dir' et 'output_dir' doivent etre definies dans config.yaml")

    log_entries: list[str] = []
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entries.append(f"=== Nettoyage lance a {ts} ===")

    print("\n--- Nettoyage des repertoires de travail ---\n")
    print(f"work_dir   : {work_dir}")
    print(f"output_dir : {output_dir}\n")

    # 1) Nettoyage brut
    clean_dir(work_dir, log_entries, "work_dir")
    clean_dir(output_dir, log_entries, "output_dir")

    # 2) Recreation de l'ossature standard
    ensure_subdirs(work_dir, WORK_SUBDIRS, log_entries, "work_dir")
    ensure_subdirs(output_dir, OUTPUT_SUBDIRS, log_entries, "output_dir")

    # 3) Ecriture du log dans output_dir
    ensure_dir(output_dir)
    log_path = os.path.join(output_dir, "clean_dirs.log")

    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("Log nettoyage work_dir / output_dir\n")
            f.write("====================================\n\n")
            for line in log_entries:
                f.write(line + "\n")
        print(f"\nLog de nettoyage ecrit dans : {log_path}")
    except Exception as e:
        print(f"\n[WARN] Impossible d'ecrire le log de nettoyage : {e}")

    print("\n--- Nettoyage termine ---\n")


# --------------------------------------------------------------------
# Script
# --------------------------------------------------------------------

if __name__ == "__main__":
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(BASE_DIR, "config.yaml")
    clean_work_and_output(config_path)
