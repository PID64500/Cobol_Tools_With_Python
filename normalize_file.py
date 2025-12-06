#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
normalize_file.py
-----------------
Etape 2 : normalisation d'un source COBOL pour analyse.

Fonction principale :
  - normalize_file(input_file, work_dir, input_encoding, output_encoding)

Règles :
  - Ignorer :
      * lignes commentaire (colonne 7 = '*')
      * lignes commençant par 'SMASH' en colonnes 1-5
      * lignes commençant par '//' (JCL éventuel)
      * lignes vides dans la zone code (colonnes 8-72)
  - Colonnes 1-6 : numéro de séquence 000001..999999
  - Colonnes 7-72 : conservées telles quelles
  - Colonnes 73-80 : espaces
  - Sortie : fichier <work_dir>/<nom_source>.etude
"""

import os
from typing import Optional


def normalize_file(
    input_file: str,
    work_dir: str,
    input_encoding: str = "latin-1",
    output_encoding: str = "latin-1",
    seq_start: int = 1,
) -> Optional[str]:
    """
    Normalise un source COBOL et écrit le .etude dans work_dir.

    :param input_file: chemin du fichier COBOL d'origine
    :param work_dir: repertoire de sortie pour le .etude
    :param input_encoding: encodage du fichier d'entrée
    :param output_encoding: encodage du fichier de sortie
    :param seq_start: numero de sequence initial (par defaut 1)
    :return: chemin complet du fichier .etude genere, ou None en cas d'erreur
    """
    os.makedirs(work_dir, exist_ok=True)

    base_name = os.path.basename(input_file)
    output_file = os.path.join(work_dir, base_name + ".etude")

    try:
        with open(input_file, "r", encoding=input_encoding, errors="ignore") as fin:
            lines = fin.readlines()
    except Exception as e:
        print(f"[ERREUR] Lecture {input_file} : {e}")
        return None

    out_lines = []
    seq = seq_start

    for raw in lines:
        line = raw.rstrip("\n")

        # On s'assure d'avoir au moins 80 colonnes pour manipuler tranquillement
        if len(line) < 80:
            line = line.ljust(80)
        else:
            line = line[:80]

        # Colonne 7 = index 6
        if line[6] == "*":
            # Ligne commentaire : on l'ignore complètement
            continue

        # Ignorer les lignes SMASH en colonne 1-5
        if line.startswith("SMASH"):
            continue

        # Ignorer les lignes '//' en colonne 1-2 (JCL residuel par exemple)
        if line.startswith("//"):
            continue

        # Si la ligne est vide dans la zone code (col 8-72), ignorer la ligne
        code_area = line[7:72].strip()
        if code_area == "":
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

    try:
        with open(output_file, "w", encoding=output_encoding, errors="ignore") as fout:
            fout.writelines(out_lines)
        print(f"[OK] Normalisé : {output_file}")
        return output_file
    except Exception as e:
        print(f"[ERREUR] Ecriture {output_file} : {e}")
        return None


# Mode autonome éventuel (optionnel)
if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        print("Usage : python normalize_file.py <source.cbl> <work_dir>")
        sys.exit(1)

    normalize_file(sys.argv[1], sys.argv[2])
