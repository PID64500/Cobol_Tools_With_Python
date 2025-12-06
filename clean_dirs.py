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
"""

import os
import shutil
from typing import Dict, List


def ensure_dir(path: str) -> None:
    """Cree le repertoire s'il n'existe pas deja."""
    os.makedirs(path, exist_ok=True)


def clean_dir(path: str, log: List[str], label: str) -> None:
    """
    Supprime tout le contenu du repertoire (fichiers ET sous-dossiers).
    Le repertoire lui-meme est conserve.

    :param path: chemin du repertoire a nettoyer
    :param log: liste de strings dans laquelle on enregistre les operations
    :param label: etiquette (work_dir / output_dir) pour le log
    """
    ensure_dir(path)

    entries = os.listdir(path)
    log.append(f"--- Contenu AVANT nettoyage ({label}) : {path}")
    if entries:
        for name in entries:
            log.append(f"  PRESENT : {name}")
    else:
        log.append("  (vide)")

    print(f"\n  --- Contenu AVANT nettoyage dans {path} ---")
    if entries:
        for name in entries:
            print(f"    - {name}")
    else:
        print("    (vide)")

    # Suppression
    for name in entries:
        full = os.path.join(path, name)
        try:
            if os.path.isfile(full) or os.path.islink(full):
                os.remove(full)
                msg = f"[Fichier supprime] {label} : {name}"
                print(f"    {msg}")
                log.append(msg)
            elif os.path.isdir(full):
                shutil.rmtree(full)
                msg = f"[Dossier supprime] {label} : {name}"
                print(f"    {msg}")
                log.append(msg)
        except Exception as e:
            msg = f"[WARN] Impossible de supprimer {full} : {e}"
            print(f"    {msg}")
            log.append(msg)

    after = os.listdir(path)
    log.append(f"--- Contenu APRES nettoyage ({label}) : {path}")
    if after:
        for name in after:
            log.append(f"  RESTE : {name}")
    else:
        log.append("  (vide)")

    print(f"\n  --- Contenu APRES nettoyage dans {path} ---")
    if after:
        for name in after:
            print(f"    - {name}")
    else:
        print("    (vide)")


def clean_work_and_output(config: Dict) -> None:
    """
    Nettoie work_dir et output_dir definis dans config.yaml,
    puis ecrit un log dans output_dir/clean_dirs.log.
    """
    work_dir = os.path.abspath(config.get("work_dir", "./work"))
    output_dir = os.path.abspath(config.get("output_dir", "./output"))

    # Liste des messages de log (on les ecrira a la fin)
    log_entries: List[str] = []

    print(f"Nettoyage du dossier de travail : {work_dir}")
    log_entries.append(f"=== Nettoyage work_dir : {work_dir}")
    clean_dir(work_dir, log_entries, "work_dir")

    print(f"\nNettoyage du dossier de sortie : {output_dir}")
    log_entries.append(f"\n=== Nettoyage output_dir : {output_dir}")
    clean_dir(output_dir, log_entries, "output_dir")

    # A la fin, on ecrit le log dans output_dir/clean_dirs.log
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
