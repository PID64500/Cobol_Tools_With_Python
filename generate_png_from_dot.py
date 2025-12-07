# generate_png_from_dot.py

import os
import subprocess
import yaml
import sys


def load_config(config_path: str) -> dict:
    """Charge le config.yaml."""
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"❌ Impossible de lire {config_path} : {e}")
        sys.exit(1)


def find_output_dir(config: dict) -> str:
    """Résout le output_dir depuis les différentes syntaxes possibles."""
    return (
        config.get("output_dir")
        or config.get("paths", {}).get("output_dir")
        or "./output"
    )


def generate_png(dot_file: str, png_file: str):
    """Appelle la commande Graphviz pour générer un PNG."""
    cmd = ["dot", "-Tpng", dot_file, "-o", png_file]

    try:
        subprocess.run(cmd, check=True)
        print(f"✅ PNG généré : {png_file}")
    except subprocess.CalledProcessError as e:
        print(f"❌ Erreur Graphviz pour : {dot_file}")
        print(f"   {e}")
    except FileNotFoundError:
        print("❌ La commande 'dot' n'est pas trouvée.")
        print("👉 Installe Graphviz et ajoute-le au PATH (redémarre le terminal).")
        sys.exit(1)


def generate_pngs_from_config(config: dict):
    """
    Génère les PNG pour tous les .dot trouvés dans output_dir
    à partir d'une config déjà chargée.
    """
    output_dir = find_output_dir(config)

    if not os.path.isdir(output_dir):
        print(f"❌ Le répertoire output_dir n'existe pas : {output_dir}")
        return

    print(f"📁 Répertoire recherché : {output_dir}")

    dot_files = [f for f in os.listdir(output_dir) if f.lower().endswith(".dot")]
    if not dot_files:
        print("⚠ Aucun fichier .dot trouvé.")
        return

    print(f"🔍 {len(dot_files)} fichier(s) .dot trouvé(s). Génération des PNG...\n")

    for dot in dot_files:
        dot_path = os.path.join(output_dir, dot)
        png_path = dot_path.replace(".dot", ".png")
        generate_png(dot_path, png_path)

    print("\n🎉 Conversion terminée.")


def main():
    # Utilisation en mode script autonome
    config = load_config("config.yaml")
    generate_pngs_from_config(config)


if __name__ == "__main__":
    main()
