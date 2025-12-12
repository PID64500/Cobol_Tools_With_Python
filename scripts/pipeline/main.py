"""
main.py – Orchestration du pipeline d'analyse COBOL
"""

import sys
import logging
import subprocess
from pathlib import Path
import yaml

import clean_dirs
import list_sources
import normalize_file
import program_structure
import build_data_dictionary
import scan_variable_usage
import analyse_structures_logiques  # ← AJOUT

logger = logging.getLogger(__name__)


# ============================================================
#   Utilitaires
# ============================================================

def load_config(config_path: Path) -> dict:
    """
    Charge le fichier config.yaml et renvoie un dict.

    On attend typiquement une structure :

    source_dir: "..."
    work_dir:   "..."
    output_dir: "..."

    logging:
      level: INFO
    """
    if not config_path.is_file():
        raise FileNotFoundError(f"Fichier de configuration introuvable : {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    if not isinstance(config, dict):
        raise TypeError(
            f"Le fichier de configuration {config_path} ne contient pas un dictionnaire YAML valide."
        )

    return config


def setup_logging(log_level: str | int = "INFO") -> None:
    """
    Initialise le logging de manière centralisée.
    """
    if isinstance(log_level, str):
        log_level = getattr(logging, log_level.upper(), logging.INFO)

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ============================================================
#   Conversions Markdown -> ODT / DOCX via pandoc
# ============================================================

def convert_markdown_to_odt_docx(
    reports_dir: Path,
    generate_odt: bool = True,
    generate_docx: bool = False,
) -> None:
    """
    Parcourt reports_dir, et pour chaque .md :

      - génère un .odt si generate_odt = True
      - génère un .docx si generate_docx = True

    en utilisant pandoc.
    """
    for md_file in sorted(reports_dir.glob("*.md")):
        if generate_odt:
            odt_file = md_file.with_suffix(".odt")
        else:
            odt_file = None

        if generate_docx:
            docx_file = md_file.with_suffix(".docx")
        else:
            docx_file = None

        cmd = ["pandoc", str(md_file)]
        if odt_file:
            cmd.extend(["-o", str(odt_file)])
        if docx_file:
            # Si on veut générer les deux, on doit appeler pandoc deux fois
            # Pour l'instant, on privilégie ODT.
            pass

        logger.info("  pandoc : %s -> %s", md_file.name, odt_file.name if odt_file else "aucun")
        try:
            subprocess.run(cmd, check=True)
        except Exception as e:
            logger.error("Erreur pandoc pour %s : %s", md_file, e)


# ============================================================
#   Pipeline principal
# ============================================================

def run_pipeline(config: dict) -> None:
    """
    Orchestration complète du pipeline, étape par étape.

    On s'appuie sur la config YAML, typiquement :

    source_dir: "C:/.../sources_cobol"
    work_dir:   "C:/.../cobol_tools_files/cobol_work"
    output_dir: "C:/.../cobol_tools_files/reports"

    + section logging (déjà gérée avant l'appel).
    """

    source_dir = Path(config["source_dir"]).resolve()
    work_dir = Path(config["work_dir"]).resolve()
    output_dir = Path(config["output_dir"]).resolve()

    etude_dir = work_dir / "etude"
    csv_dir = work_dir / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)
    reports_dir = output_dir
    reports_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Répertoires :")
    logger.info("  source_dir  = %s", source_dir)
    logger.info("  work_dir    = %s", work_dir)
    logger.info("  output_dir  = %s", output_dir)

    # 1) Nettoyage / préparation des dossiers
    logger.info("Étape 1/11 – Nettoyage / préparation des répertoires de travail")
    clean_dirs.clean_work_and_output(config)

    # 2) Listing des sources COBOL
    logger.info("Étape 2/11 – Listing des sources COBOL")
    source_files = list_sources.list_cobol_sources(config)
    logger.info("  %d fichier(s) COBOL détecté(s)", len(source_files))

    # 3) Normalisation des sources (.etude)
    logger.info("Étape 3/11 – Normalisation des sources (.etude)")
    normalized_files = normalize_file.normalize_list_files(
        source_files=source_files,
        config=config,
    )
    logger.info("  %d fichier(s) .etude généré(s)", len(normalized_files))
    
    import build_program_dd_and_copybooks

    # 4) Exploitation .etude pour référentiel COPYBOOK
    dd_paths = build_program_dd_and_copybooks.generate_dd_and_copybooks(config)
    logging.getLogger(__name__).info("✅ DD générés: %s", dd_paths)

    # 5) Structure des programmes : program_structure.csv
    logger.info("Étape 4/11 – Génération de program_structure.csv (structure des paragraphes)")

    program_structure_csv = program_structure.generate_program_structure(work_dir)

    logger.info("  program_structure.csv généré : %s", program_structure_csv)

    # 6) Branche DATA – Construction des dictionnaires de données
    logger.info("Étape 5/11 – Construction des dictionnaires de données (branche DATA – build_data_dictionary)")

    # Exemple : un dictionnaire global, et un dictionnaire par programme
    data_dict_global = csv_dir / "data_dictionary_global.csv"
    data_dict_by_program_dir = csv_dir / "dd_by_program"
    data_dict_by_program_dir.mkdir(parents=True, exist_ok=True)

    build_data_dictionary.build_data_dictionaries(
        normalized_files=normalized_files,
        program_structure_csv=program_structure_csv,
        global_dd_path=data_dict_global,
        dd_by_program_dir=data_dict_by_program_dir,
    )

    # 7) Branche DATA – Scan des usages de variables
    logger.info("Étape 6/11 – Scan des usages de variables (branche DATA – scan_variable_usage)")

    for etude_entry in normalized_files:
        etude_path = Path(etude_entry)
        name = etude_path.name

        # Nom du programme sans extensions .cbl.etude / .etude
        program = name
        for suffix in [".cbl.etude", ".CBL.ETUDE", ".etude", ".ETUDE"]:
            if program.endswith(suffix):
                program = program[: -len(suffix)]
                break

        logger.info("  Analyse des usages pour le programme %s", program)

        # Dictionnaire de données du programme
        dd_path = data_dict_by_program_dir / f"{program}_dd.csv"
        if not dd_path.is_file():
            logger.warning("    Pas de dictionnaire de données pour %s (fichier %s introuvable)", program, dd_path)
            continue

        variables = scan_variable_usage.load_dd_file(dd_path)
        paragraph_ranges = scan_variable_usage.load_paragraph_ranges(program_structure_csv, program)

        # .etude : on utilise le chemin déjà normalisé
        usages = scan_variable_usage.process_etude(program, variables, paragraph_ranges, etude_path)

        # Écriture du PROGRAM_usage.csv dans csv_dir
        scan_variable_usage.write_usage_csv(program, usages, csv_dir)

    # 7) Branche DATA – Analyse des structures logiques
    logger.info("Étape 7/11 – Analyse des structures logiques (branche DATA – analyse_structures_logiques)")

    for etude_entry in normalized_files:
        etude_path = Path(etude_entry)
        name = etude_path.name

        program = name
        for suffix in [".cbl.etude", ".CBL.ETUDE", ".etude", ".ETUDE"]:
            if program.endswith(suffix):
                program = program[: -len(suffix)]
                break

        logger.info("  Structures logiques pour le programme %s", program)

        analyse_structures_logiques.analyse_program(
            program=program,
            etude_path=etude_path,
            csv_dir=csv_dir,
            program_structure_csv=program_structure_csv,
        )

    # 8) Rapports Markdown (synthèse par programme)
    logger.info("Étape 8/11 – Génération des rapports Markdown")
    # Ici tu appelles ton générateur de rapports markdown par programme
    # Exemple : report_markdown.make_markdown_report(...)

    # 9) Conversion Markdown -> ODT / DOCX
    logger.info("Étape 9/11 – Conversion Markdown -> ODT (pandoc)")
    convert_markdown_to_odt_docx(
        reports_dir=reports_dir,
        generate_odt=True,
        generate_docx=False,
    )

    # 10) Étape 10 et 11 : réservées pour futures branches (graphes, synthèse globale...)
    logger.info("Étape 10/11 – (Réservée pour futures analyses : graphes, appels, etc.)")
    logger.info("Étape 11/11 – Pipeline terminé ✅")


# ============================================================
#   Entrée principale
# ============================================================

def main() -> int:
    # 1) Chemin du fichier de config (par défaut : config.yaml dans le cwd)
    if len(sys.argv) > 1:
        config_path = Path(sys.argv[1]).resolve()
    else:
        config_path = Path("config.yaml").resolve()

    # 2) Chargement de la config
    config = load_config(config_path)

    # 3) Initialisation du logging
    log_cfg = (config.get("logging") or {})
    log_level = log_cfg.get("level", "INFO")
    setup_logging(log_level)

    logger.info("Démarrage du pipeline d'analyse COBOL")
    logger.info("Configuration chargée depuis %s", config_path)

    try:
        run_pipeline(config)
    except Exception as e:
        logging.exception("❌ Erreur dans le pipeline : %s", e)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
