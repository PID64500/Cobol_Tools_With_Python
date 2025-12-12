from pathlib import Path

# 🔧 Répertoire contenant les fichiers .etude
ETUDE_DIR = Path(r"C:\Users\Utilisateur\Documents\Workplace\cobol_tools_files\cobol_work\etude")

# 🔧 Fichier de sortie
OUTPUT_FILE = Path("exec.txt")


def collect_exec_patterns(etude_path: Path, exec_patterns: set):
    """
    Parcourt un fichier .etude et ajoute dans exec_patterns
    les motifs 'EXEC XXX YYY' trouvés en tête de ligne de code.
    """
    in_proc_div = False

    with etude_path.open("r", encoding="latin-1", errors="ignore") as f:
        for line in f:
            # On commence après PROCEDURE DIVISION
            if "PROCEDURE DIVISION" in line:
                in_proc_div = True
                continue

            if not in_proc_div:
                continue

            # Zone code COBOL : colonnes 12 à 72 (index 11 à 71)
            code = line[11:72].strip()
            if not code:
                continue

            parts = code.split()
            if len(parts) < 3:
                continue

            # EXEC en premier mot ?
            if parts[0].upper() != "EXEC":
                continue

            # On prend les 3 premiers mots : EXEC XXX YYY
            pattern = f"{parts[0].upper()} {parts[1].upper()} {parts[2].upper()}"
            exec_patterns.add(pattern)


def main():
    exec_patterns = set()

    # Scan de tous les .etude
    for etude_file in ETUDE_DIR.glob("*.etude"):
        collect_exec_patterns(etude_file, exec_patterns)

    # Tri alphabétique
    sorted_patterns = sorted(exec_patterns)

    # Affichage console
    print("=== Motifs EXEC détectés ===\n")
    for pat in sorted_patterns:
        print(pat)
    print(f"\nTotal motifs EXEC uniques : {len(sorted_patterns)}")

    # Écriture dans exec.txt
    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        f.write("=== Motifs EXEC détectés ===\n\n")
        for pat in sorted_patterns:
            f.write(pat + "\n")
        f.write(f"\nTotal motifs EXEC uniques : {len(sorted_patterns)}\n")

    print(f"\n📄 Résultat écrit dans : {OUTPUT_FILE.resolve()}")


if __name__ == "__main__":
    main()
