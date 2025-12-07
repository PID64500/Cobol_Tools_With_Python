"""
main.py – Orchestration du pipeline d'analyse COBOL
"""

import sys
import logging
from pathlib import Path

import yaml

import clean_dirs
import list_sources
import normalize_file
import extract_paragraphs
import scan_interactions
import find_callers
import analysis_core_wrapper
import graph_builder
import report_markdown
from generate_png_from_dot import generate_pngs_from_config


def load_config(config_path: Path) -> dict:
    if not config_path.is_file():
        raise FileNotFoundError(f"Fichier de configuration introuvable : {config_path}")
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def setup_logging(config: dict) -> None:
    logging_cfg = config.get("logging", {}) or {}
    enabled = logging_cfg.get("enabled", True)
    if not enabled:
        logging.disable(logging.CRITICAL)
        return

    level_name = logging_cfg.get("level", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    to_file = logging_cfg.get("to_file", True)
    file_path = logging_cfg.get("file_path", "cobol_tools.log")

    handlers: list[logging.Handler] = []

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    handlers.append(console_handler)

    if to_file:
        log_path = Path(file_path).resolve()
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        handlers.append(file_handler)

    logging.basicConfig(level=level, handlers=handlers)


def run_pipeline(config: dict) -> None:
    logger = logging.getLogger(__name__)

    # 1) Nettoyage / préparation des dossiers
    logger.info("Étape 1/10 – Nettoyage / préparation des répertoires de travail")
    clean_dirs.clean_work_and_output(config)

    # 2) Listing des sources COBOL
    logger.info("Étape 2/10 – Listing des sources COBOL")
    source_files = list_sources.list_cobol_sources(config)
    logger.info("  %d fichier(s) COBOL détecté(s)", len(source_files))

    # 3) Normalisation
    logger.info("Étape 3/10 – Normalisation des fichiers")
    normalized_files = normalize_file.normalize_list_files(source_files, config)
    logger.info("  %d fichier(s) normalisé(s)", len(normalized_files))

    # 4) Extraction des paragraphes (pour les autres analyses)
    logger.info("Étape 4/10 – Extraction des paragraphes")
    paragraphs_info = extract_paragraphs.extract_from_files(normalized_files)
    logger.info("  Extraction des paragraphes terminée")

    # 5) Scan des interactions directement dans les fichiers normalisés
    logger.info("Étape 5/10 – Scan des interactions CICS")
    interactions_by_prog = scan_interactions.scan_from_files(
        normalized_files,
        config,
    )
    logger.info("  Scan des interactions terminé")

    # Log détaillé des interactions (mode test)
    if not interactions_by_prog:
        logger.info("INTERACTIONS : aucune interaction détectée.")
    else:
        logger.info("INTERACTIONS : détail par programme")
        for prog, pts in interactions_by_prog.items():
            logger.info("INTERACTIONS - Programme %s : %d point(s)", prog, len(pts))
            for p in pts:
                logger.info(
                    "  [%s] seq=%s cat=%s kind=%s mapset=%s map=%s source=%s raw=%s",
                    p.program,
                    p.seq,
                    p.category,
                    p.kind,
                    p.mapset_name,
                    p.map_name,
                    p.source,
                    p.raw.strip(),
                )

    # 6) Recherche des débranchements / appels internes (GOTO / PERFORM)
    logger.info("Étape 6/10 – Analyse débranchements GOTO / PERFORM")
    callers_info = find_callers.find_call_relations(paragraphs_info, config)
    logger.info("  Analyse des débranchements terminée")

    # 7) Analyse centrale
    logger.info("Étape 7/10 – Analyse centrale (analysis_core)")
    analysis_result = analysis_core_wrapper.run_analysis(
        normalized_files,
        paragraphs_info,
        interactions_by_prog,
        callers_info,
        config,
    )
    logger.info("  Analyse centrale terminée")

    # 8) Construction des graphes
    logger.info("Étape 8/10 – Construction des graphes")
    dot_paths = []
    for f in normalized_files:
        logger.info("  Construction du graphe pour %s", f)
        dot_path = graph_builder.generate_graph_for_file(str(f), config)
        dot_paths.append(dot_path)
    logger.info("  %d graphe(s) généré(s)", len(dot_paths))


    # 9) Génération du rapport Markdown
    logger.info("Étape 9/10 – Génération du rapport Markdown")

    # On récupère un répertoire de sortie cohérent
    output_dir = (
        config.get("output_dir")                           # cas simple
        or config.get("paths", {}).get("output_dir")       # si tu as un bloc paths:
        or "./output"
    )

    report_paths = []
    for f in normalized_files:
        logger.info("  Rapport Markdown pour %s", f)
        rp = report_markdown.make_markdown_report(str(f), output_dir)
        report_paths.append(rp)
        logger.info("    → %s", rp)

    logger.info("  %d rapport(s) généré(s)", len(report_paths))

# 10) Génération optionnelle des PNG Graphviz
    if config.get("generate_png_graphs", False):
        logger.info("Étape 10/10 – Génération des PNG Graphviz")
        try:
            generate_pngs_from_config(config)
            logger.info("✅ PNG Graphviz générés (si .dot présents)")
        except Exception:
            logger.exception("❌ Erreur lors de la génération des PNG Graphviz")
    else:
        logger.info("Étape 10/10 – Génération des PNG Graphviz désactivée (generate_png_graphs = false)")
        

def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]

    project_root = Path(__file__).resolve().parent
    config_path = project_root / "config.yaml"

    try:
        config = load_config(config_path)
    except Exception as e:
        print(f"Erreur lors du chargement de la configuration : {e}", file=sys.stderr)
        return 1

    setup_logging(config)
    logger = logging.getLogger(__name__)
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
