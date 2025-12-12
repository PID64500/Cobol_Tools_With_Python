import os
from pathlib import Path

# Répertoire contenant les .etude
ETUDE_DIR = Path(r"C:\Users\Utilisateur\Documents\Workplace\cobol_tools_files\cobol_work\etude")

# Fichier résultat
OUTPUT_FILE = Path("instructions_cobol.txt")

def extract_instructions_from_file(path: Path, instructions: set):
    in_proc_div = False

    with path.open("r", encoding="latin-1", errors="ignore") as f:
        for line in f:
            # Détection de PROCEDURE DIVISION
            if "PROCEDURE DIVISION" in line:
                in_proc_div = True
                continue

            if not in_proc_div:
                continue

            # Zone code COBOL = colonnes 12 à 72
            code = line[11:72].strip()
            if not code:
                continue

            parts = code.split()

            instr = parts[0].upper()

            if instr.endswith('.'):
                continue

            if not instr[0].isalpha():
                continue   # on ignore
            
            instructions.add(instr)


def main():
    instructions = set()

    for file in ETUDE_DIR.glob("*.etude"):
        extract_instructions_from_file(file, instructions)

    # Tri : longueur décroissante, puis alphabétique
    sorted_instr = sorted(instructions, key=lambda x: (-len(x), x))

    # Affichage console
    print("=== Instructions COBOL brutes détectées ===\n")
    for instr in sorted_instr:
        print(instr)

    print(f"\nTotal instructions uniques : {len(sorted_instr)}")

    # Écriture dans le fichier TXT
    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        f.write("=== Instructions COBOL brutes détectées ===\n\n")
        for instr in sorted_instr:
            f.write(instr + "\n")
        f.write(f"\nTotal instructions uniques : {len(sorted_instr)}\n")

    print(f"\n📄 Résultat écrit dans : {OUTPUT_FILE.resolve()}")


if __name__ == "__main__":
    main()
