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
import extract_paragraphs
import scan_interactions
import find_callers
import analysis_core_wrapper
import graph_builder
import report_markdown
import generate_global_synthesis
from generate_png_from_dot import generate_pngs_from_config


# ============================================================
#   Chargement configuration & logging
# ============================================================

def load_config(config_path: Path) -> dict:
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

def convert_md_to_odt(
    md_path: Path,
    odt_path: Path,
    template: str | None = None,
    pandoc_exe: str = "pandoc",
    lang: str | None = None,
) -> None:
    """
    Convertit un fichier Markdown en ODT via pandoc.
    Utilise éventuellement :
      - un template ODT (reference-doc)
      - un paramètre de langue (ex: fr-FR)
    """
    logger = logging.getLogger(__name__)
    cmd = [pandoc_exe, str(md_path), "-o", str(odt_path)]
    if template:
        cmd.extend(["--reference-doc", template])
    if lang:
        # Indique à pandoc la langue du document (LibreOffice verra fr-FR)
        cmd.extend(["-V", f"lang={lang}"])

    logger.info("Conversion ODT : %s -> %s", md_path, odt_path)
    try:
        subprocess.run(cmd, check=True)
    except Exception as e:
        logger.error("Erreur lors de la conversion ODT (%s) : %s", md_path, e)


def convert_md_to_docx(
    md_path: Path,
    docx_path: Path,
    template: str | None = None,
    pandoc_exe: str = "pandoc",
    lang: str | None = None,
) -> None:
    """
    Convertit un fichier Markdown en DOCX via pandoc.
    On peut aussi passer la langue (certains outils l'exploitent).
    """
    logger = logging.getLogger(__name__)
    cmd = [pandoc_exe, str(md_path), "-o", str(docx_path)]
    if template:
        cmd.extend(["--reference-doc", template])
    if lang:
        cmd.extend(["-V", f"lang={lang}"])

    logger.info("Conversion DOCX : %s -> %s", md_path, docx_path)
    try:
        subprocess.run(cmd, check=True)
    except Exception as e:
        logger.error("Erreur lors de la conversion DOCX (%s) : %s", md_path, e)


# ============================================================
#   Pipeline principal
# ============================================================

def run_pipeline(config: dict) -> None:
    logger = logging.getLogger(__name__)

    # 1) Nettoyage / préparation des dossiers
    logger.info("Étape 1/11 – Nettoyage / préparation des répertoires de travail")
    clean_dirs.clean_work_and_output(config)

    # 2) Listing des sources COBOL
    logger.info("Étape 2/11 – Listing des sources COBOL")
    source_files = list_sources.list_cobol_sources(config)
    logger.info("  %d fichier(s) COBOL détecté(s)", len(source_files))

    # 3) Normalisation
    logger.info("Étape 3/11 – Normalisation des fichiers")
    normalized_files = normalize_file.normalize_list_files(source_files, config)
    logger.info("  %d fichier(s) normalisé(s)", len(normalized_files))

    # 4) Extraction des paragraphes (pour les autres analyses)
    logger.info("Étape 4/11 – Extraction des paragraphes")
    paragraphs_info = extract_paragraphs.extract_from_files(normalized_files)
    logger.info("  Extraction des paragraphes terminée")

    # 5) Scan des interactions directement dans les fichiers normalisés
    logger.info("Étape 5/11 – Scan des interactions CICS")
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
    logger.info("Étape 6/11 – Analyse débranchements GOTO / PERFORM")
    callers_info = find_callers.find_call_relations(paragraphs_info, config)
    logger.info("  Analyse des débranchements terminée")

    # 7) Analyse centrale
    logger.info("Étape 7/11 – Analyse centrale (analysis_core)")
    analysis_result = analysis_core_wrapper.run_analysis(
        normalized_files,
        paragraphs_info,
        interactions_by_prog,
        callers_info,
        config,
    )
    logger.info("  Analyse centrale terminée")

    # 8) Construction des graphes (.dot)
    logger.info("Étape 8/11 – Construction des graphes")
    dot_paths: list[Path] = []
    for f in normalized_files:
        logger.info("  Construction du graphe pour %s", f)
        dot_path = graph_builder.generate_graph_for_file(str(f), config)
        dot_paths.append(Path(dot_path))
    logger.info("  %d graphe(s) généré(s)", len(dot_paths))

    # 9) Génération des rapports Markdown
    logger.info("Étape 9/11 – Génération du rapport Markdown")

    output_dir = (
        config.get("output_dir")
        or config.get("paths", {}).get("output_dir")
        or "./output"
    )
    output_dir_path = Path(output_dir).resolve()

    report_paths: list[str] = []
    for f in normalized_files:
        logger.info("  Génération du rapport Markdown pour %s", f)
        rp = report_markdown.make_markdown_report(str(f), str(output_dir_path))
        report_paths.append(rp)
    logger.info("  %d rapport(s) Markdown généré(s)", len(report_paths))

    # 10) Conversions optionnelles vers ODT / DOCX (config.report.outputs + config.pandoc)
    report_cfg = config.get("report", {}) or {}
    outputs_cfg = report_cfg.get("outputs", []) or [{"format": "md"}]

    pandoc_cfg = config.get("pandoc", {}) or {}
    pandoc_exe = pandoc_cfg.get("exe", "pandoc")
    pandoc_lang = pandoc_cfg.get("lang", "fr-FR")  # langue par défaut

    for out_cfg in outputs_cfg:
        # On accepte soit une string ("md"), soit un dict {format: "md", template: "..."}
        if isinstance(out_cfg, str):
            fmt = out_cfg.lower().strip()
            template = None
        elif isinstance(out_cfg, dict):
            fmt = str(out_cfg.get("format", "md")).lower().strip()
            template = out_cfg.get("template")  # peut être None
        else:
            logger.warning("Format de sortie ignoré (type inattendu) : %r", out_cfg)
            continue

        if fmt == "odt":
            logger.info("Étape 10/11 – Conversion Markdown -> ODT via pandoc")
            for rp in report_paths:
                md_path = Path(rp)
                odt_path = md_path.with_suffix(".odt")
                convert_md_to_odt(
                    md_path,
                    odt_path,
                    template,
                    pandoc_exe=pandoc_exe,
                    lang=pandoc_lang,
                )

        elif fmt == "docx":
            logger.info("Étape 10/11 – Conversion Markdown -> DOCX via pandoc")
            for rp in report_paths:
                md_path = Path(rp)
                docx_path = md_path.with_suffix(".docx")
                convert_md_to_docx(
                    md_path,
                    docx_path,
                    template,
                    pandoc_exe=pandoc_exe,
                    lang=pandoc_lang,
                )

        elif fmt == "md":
            logger.info("Format MD : aucune conversion nécessaire")

        else:
            logger.warning("Format inconnu dans config.report.outputs : %r", fmt)

    # 10) Génération optionnelle des PNG Graphviz
    if config.get("generate_png_graphs", False):
        logger.info("Étape 10/11 – Génération des PNG Graphviz")
        try:
            generate_pngs_from_config(config)
            logger.info("✅ PNG Graphviz générés (si .dot présents)")
        except Exception:
            logger.exception("❌ Erreur lors de la génération des PNG Graphviz")
    else:
        logger.info(
            "Étape 10/11 – Génération des PNG Graphviz désactivée "
            "(generate_png_graphs = false)"
        )

    # 11) Synthèse globale multi-programmes
    logger.info("Étape 11/11 – Synthèse globale (CSV + Markdown)")

    global_cfg = config.get("global_synthesis", {}) or {}
    enabled = global_cfg.get("enabled", True)

    if not enabled:
        logger.info(
            "Synthèse globale désactivée (global_synthesis.enabled = false)"
        )
    else:
        try:
            output_dir = (
                config.get("output_dir")
                or config.get("paths", {}).get("output_dir")
                or "./output"
            )
            output_dir_path = Path(output_dir).resolve()

            etude_paths: list[Path] = []
            for f in normalized_files:
                if isinstance(f, (str, Path)):
                    etude_paths.append(Path(f))
                elif isinstance(f, dict):
                    for key in ("etude_path", "normalized_path", "path", "file", "filename"):
                        if key in f and f[key]:
                            etude_paths.append(Path(f[key]))
                            break

            metrics = generate_global_synthesis.analyze_files(etude_paths)
            csv_path = generate_global_synthesis.write_csv(metrics, output_dir_path)
            md_path = generate_global_synthesis.write_global_markdown(metrics, output_dir_path)

            logger.info("✅ Synthèse globale générée : %s", csv_path)
            logger.info("✅ Rapport global Markdown généré : %s", md_path)

            # ---- Conversion du rapport global en ODT / DOCX ----
            for out_cfg in outputs_cfg:
                # même logique que pour les rapports individuels
                if isinstance(out_cfg, str):
                    fmt = out_cfg.lower().strip()
                    template = None
                elif isinstance(out_cfg, dict):
                    fmt = str(out_cfg.get("format", "md")).lower().strip()
                    template = out_cfg.get("template")
                else:
                    logger.warning("Format de sortie ignoré (type inattendu) : %r", out_cfg)
                    continue

                if fmt == "odt":
                    logger.info("Conversion du rapport global en ODT")
                    md_global = Path(md_path)
                    odt_global = md_global.with_suffix(".odt")
                    convert_md_to_odt(
                        md_global,
                        odt_global,
                        template,
                        pandoc_exe=pandoc_exe,
                        lang=pandoc_lang,
                    )

                elif fmt == "docx":
                    logger.info("Conversion du rapport global en DOCX")
                    md_global = Path(md_path)
                    docx_global = md_global.with_suffix(".docx")
                    convert_md_to_docx(
                        md_global,
                        docx_global,
                        template,
                        pandoc_exe=pandoc_exe,
                        lang=pandoc_lang,
                    )

        except Exception:
            logger.exception("❌ Erreur lors de la génération de la synthèse globale")


# ============================================================
#   Entrée principale
# ============================================================

def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]

    project_root = Path(__file__).resolve().parent
    config_path = project_root / "config.yaml"

    try:
        config = load_config(config_path)
    except Exception as e:
        print(f"Erreur lors du chargement de la configuration : {e}")
        return 1

    # On lit le niveau de log dans la section "logging" du YAML
    logging_cfg = config.get("logging", {}) or {}
    log_level = logging_cfg.get("level", "INFO")

    setup_logging(log_level=log_level)

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
