# inspect_line_copy.py

path = r"C:/Users/Utilisateur/Documents/Workplace/cobol_tools_files/cobol_source/SRSRADIS.cbl"

with open(path, "rb") as f:
    data = f.read().splitlines()

print("Nombre total de lignes :", len(data))

# Cherche la ligne contenant la chaîne "REPLACING"
for idx, raw in enumerate(data):
    if b"REPLACING" in raw or b"replacing" in raw.lower():
        print("\n=== LIGNE COPY TROUVÉE ===")
        print(f"Ligne {idx+1}: {raw}")

        print("\nHexdump caractère par caractère:")
        for i, b in enumerate(raw):
            ch = chr(b) if 32 <= b < 127 else "."
            print(f"{i:03d}: {b:02X} ({ch})")

        break
else:
    print("Aucune ligne contenant 'REPLACING' trouvée !")
