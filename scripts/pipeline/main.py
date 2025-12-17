"""
main.py – Orchestration du pipeline d'analyse COBOL
"""

from logging import config
import sys
import logging
import subprocess
import csv
from pathlib import Path
import yaml

from ..pipeline import clean_dirs
from ..pipeline import list_sources
from ..pipeline import normalize_file
from ..analysis import program_structure
from ..data_dictionnary import build_data_dictionary
from ..data_dictionnary import build_program_dd_and_copybooks
from ..analysis import scan_variable_usage  # ← brique intégrée via appel direct
from ..analysis import analyse_structures_logiques  # ← brique intégrée
from ..analysis import analyse_variables_critiques  # ← nouvelle brique
from ..analysis import scan_unused_variables  # ← Niveau 1.1 variables inutilisées
from ..analysis import analyse_redefines_dangereux  # ← Niveau 1.2 REDEFINES dangereux
from ..analysis import analyse_occurs_inutilises  # ← Niveau 1.3 OCCURS non utilisés
from ..analysis import analyse_niveaux_cobol  # ← Niveau 1.4 anomalies niveaux COBOL
from ..data import data_concepts_usage  # ← Niveau 2.1 concepts de données (pivot transverse)
from ..data import structures_cartography  # ← Niveau 2.2 cartographie des structures
from ..data import concepts_consolidation  # ← Niveau 2.C consolidation des concepts

logger = logging.getLogger(__name__)


# ============================================================
#   Utilitaires
# ============================================================

def load_config(config_path: Path) -> dict:
    """
    Charge le fichier config.yaml et renvoie un dict.
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


def _load_csv_dict_rows(csv_path: Path) -> list[dict]:
    """
    Charge un CSV en liste de dict (DictReader).
    """
    rows: list[dict] = []
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows


def _write_csv_rows(rows: list[dict], out_csv: Path) -> None:
    """
    Écrit une liste de dict dans un CSV.
    """
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    if not rows:
        # crée quand même un fichier vide (optionnel)
        out_csv.write_text("", encoding="utf-8")
        return

    # Union des clés pour éviter de perdre des colonnes si certains dict diffèrent
    fieldnames = sorted({k for r in rows for k in r.keys()})

    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


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
#   Helpers spécifiques pipeline
# ============================================================

def _program_from_usage_filename(usage_path: Path) -> str | None:
    """
    Extrait le nom de programme depuis un fichier usage nommé: XXXXXXXX_usage.csv
    """
    name = usage_path.name
    suffix = "_usage.csv"
    if not name.endswith(suffix):
        return None
    return name[: -len(suffix)].strip() or None


# ============================================================
#   Pipeline principal
# ============================================================

def run_pipeline(config: dict) -> None:
    """
    Orchestration complète du pipeline, étape par étape.
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
    logger.info("Étape 1/16 – Nettoyage / préparation des répertoires de travail")
    clean_dirs.clean_work_and_output(config)

    # 2) Listing des sources COBOL
    logger.info("Étape 2/16 – Listing des sources COBOL")
    source_files = list_sources.list_cobol_sources(config)
    logger.info("  %d fichier(s) COBOL détecté(s)", len(source_files))

    # 3) Normalisation des sources (.etude)
    logger.info("Étape 3/16 – Normalisation des sources (.etude)")
    normalized_files = normalize_file.normalize_list_files(
        source_files=source_files,
        config=config,
    )
    logger.info("  %d fichier(s) .etude généré(s)", len(normalized_files))

    # 4) Exploitation .etude pour référentiel COPYBOOK + DD program/copybooks
    logger.info("Étape 4/16 – Génération DD programme + référentiel COPYBOOK")
    dd_paths = build_program_dd_and_copybooks.generate_dd_and_copybooks(config)
    logger.info("✅ DD générés : %s", {k: str(v) for k, v in dd_paths.items()})

    # 5) Structure des programmes : program_structure.csv
    logger.info("Étape 5/16 – Génération de program_structure.csv (structure des paragraphes)")
    program_structure_csv = program_structure.generate_program_structure(work_dir)
    logger.info("  program_structure.csv généré : %s", program_structure_csv)

    # 6) Branche DATA – Construction des dictionnaires de données
    logger.info("Étape 6/16 – Construction des dictionnaires de données (build_data_dictionary)")

    data_dict_global = csv_dir / "data_dictionary_global.csv"
    data_dict_by_program_dir = csv_dir / "dd_by_program"
    data_dict_by_program_dir.mkdir(parents=True, exist_ok=True)

    build_data_dictionary.build_data_dictionary(
        normalized_files=normalized_files,
        program_structure_csv=program_structure_csv,
        global_dd_path=data_dict_global,
        dd_by_program_dir=data_dict_by_program_dir,
    )

    # 7) Scan des usages variables – appel direct
    logger.info("Étape 7/16 – Scan des usages de variables (scan_variable_usage)")

    usage_outputs = scan_variable_usage.scan_variable_usage(
        normalized_files=normalized_files,
        work_dir=str(work_dir),
        dd_by_program_dir=str(data_dict_by_program_dir),
        program_structure_csv=str(program_structure_csv),
    )

    logger.info("  %d fichier(s) usage généré(s)", len(usage_outputs))

    # 8) Analyse des structures logiques – 1 fichier par programme
    logger.info("Étape 8/16 – Analyse des structures logiques (analyse_structures_logiques)")

    structures_dir = csv_dir / "structures_logiques"
    structures_dir.mkdir(parents=True, exist_ok=True)

    structures_outputs: list[Path] = []

    for usage_csv in usage_outputs:
        usage_csv = Path(usage_csv)
        prog = _program_from_usage_filename(usage_csv)
        if not prog:
            logger.warning("  usage ignoré (nom inattendu) : %s", usage_csv.name)
            continue

        dict_csv = data_dict_by_program_dir / f"{prog}_dd.csv"
        if not dict_csv.is_file():
            logger.error("  DD manquant pour %s : %s", prog, dict_csv)
            continue

        out_csv = structures_dir / f"structures_logiques_{prog}.csv"

        try:
            analyse_structures_logiques.analyse_structures_logiques(
                dict_csv_path=dict_csv,
                usage_csv_path=usage_csv,
                out_csv_path=out_csv,
            )
            structures_outputs.append(out_csv)
        except Exception as e:
            logger.exception("  Erreur structures logiques %s : %s", prog, e)

    logger.info("  %d fichier(s) structures logiques généré(s)", len(structures_outputs))

    # 9) Analyse des variables critiques – 1 fichier par programme
    logger.info("Étape 9/16 – Analyse des variables critiques (analyse_variables_critiques)")

    variables_critiques_dir = csv_dir / "variables_critiques"
    variables_critiques_dir.mkdir(parents=True, exist_ok=True)

    nb_varcrit = 0

    for etude_path in normalized_files:
        etude_path = Path(etude_path)
        prog = etude_path.name.split(".")[0].upper()

        usage_csv = csv_dir / f"{prog}_usage.csv"
        if not usage_csv.is_file():
            logger.error("  Usage manquant pour %s : %s", prog, usage_csv)
            continue

        dict_csv = data_dict_by_program_dir / f"{prog}_dd.csv"
        if not dict_csv.is_file():
            logger.error("  DD manquant pour %s : %s", prog, dict_csv)
            continue

        out_csv = variables_critiques_dir / f"{prog}_variables_critiques.csv"

        try:
            usage_rows = analyse_variables_critiques.load_usage(usage_csv)
            dd_rows = _load_csv_dict_rows(dict_csv)

            # ✅ Appel normal (probable) : dd_rows est itérable, usage_rows aussi
            try:
                rows = analyse_variables_critiques.build_variables_critiques(dd_rows, usage_rows)
            except TypeError:
                # 🔁 Fallback si ta signature attend (etude_path, dd_rows, usage_rows)
                rows = analyse_variables_critiques.build_variables_critiques(etude_path, dd_rows, usage_rows)

            _write_csv_rows(rows, out_csv)
            nb_varcrit += 1
        except Exception as e:
            logger.exception("  Erreur variables critiques %s : %s", prog, e)

    logger.info("  %d fichier(s) variables critiques généré(s)", nb_varcrit)


    # 10) Niveau 1.1 – Détection des variables inutilisées (scan_unused_variables)
    logger.info("Étape 10/16 – Détection des variables inutilisées (scan_unused_variables)")

    try:
        out_info = scan_unused_variables.scan_unused_variables(
            csv_dir=csv_dir,
            dd_by_program_dir=data_dict_by_program_dir,
        )

        global_path = out_info.get("global")
        by_program = out_info.get("by_program", {}) or {}

        logger.info("  unused global     : %s", global_path)
        logger.info("  unused by_program : %d fichier(s) généré(s)", len(by_program))

        # Détail uniquement en DEBUG (évite de polluer un log INFO)
        for prog, path in sorted(by_program.items()):
            logger.debug("    %s -> %s", prog, path)

    except Exception as e:
        logger.exception("  Erreur scan_unused_variables : %s", e)

    # 11) Niveau 1.2 – Détection des REDEFINES dangereux
    logger.info("Étape 11/16 – Détection des REDEFINES dangereux (analyse_redefines_dangereux)")

    redefines_dir = csv_dir / "redefines_dangereux"
    redefines_dir.mkdir(parents=True, exist_ok=True)

    nb_redef = 0
    for etude_path in normalized_files:
        prog = Path(etude_path).name.split(".")[0].upper()
        usage_csv = csv_dir / f"{prog}_usage.csv"
        dict_csv = data_dict_by_program_dir / f"{prog}_dd.csv"
        if not usage_csv.is_file() or not dict_csv.is_file():
            continue

        out_csv = redefines_dir / f"{prog}_redefines_dangereux.csv"
        try:
            analyse_redefines_dangereux.analyse_redefines_dangereux(
                dd_csv_path=dict_csv,
                usage_csv_path=usage_csv,
                out_csv_path=out_csv,
            )
            nb_redef += 1
        except Exception as e:
            logger.exception("  Erreur redefines %s : %s", prog, e)

    logger.info("  %d fichier(s) REDEFINES dangereux généré(s)", nb_redef)

    # 12) Niveau 1.3 – Détection des OCCURS non utilisés
    logger.info("Étape 12/16 – Détection des OCCURS non utilisés (analyse_occurs_inutilises)")

    occurs_dir = csv_dir / "occurs_inutilises"
    occurs_dir.mkdir(parents=True, exist_ok=True)

    nb_occ = 0
    for etude_path in normalized_files:
        prog = Path(etude_path).name.split(".")[0].upper()
        usage_csv = csv_dir / f"{prog}_usage.csv"
        dict_csv = data_dict_by_program_dir / f"{prog}_dd.csv"
        if not usage_csv.is_file() or not dict_csv.is_file():
            continue

        out_csv = occurs_dir / f"{prog}_occurs_inutilises.csv"
        try:
            analyse_occurs_inutilises.analyse_occurs_inutilises(
                dd_csv_path=dict_csv,
                usage_csv_path=usage_csv,
                out_csv_path=out_csv,
            )
            nb_occ += 1
        except Exception as e:
            logger.exception("  Erreur occurs %s : %s", prog, e)

    logger.info("  %d fichier(s) OCCURS non utilisés généré(s)", nb_occ)

    # 13) Niveau 1.4 – Anomalies de niveaux COBOL
    logger.info("Étape 13/16 – Détection des anomalies de niveaux COBOL (analyse_niveaux_cobol)")

    levels_dir = csv_dir / "anomalies_niveaux"
    levels_dir.mkdir(parents=True, exist_ok=True)

    nb_lvl = 0
    for etude_path in normalized_files:
        prog = Path(etude_path).name.split(".")[0].upper()
        dict_csv = data_dict_by_program_dir / f"{prog}_dd.csv"
        if not dict_csv.is_file():
            continue

        out_csv = levels_dir / f"{prog}_anomalies_niveaux.csv"
        try:
            analyse_niveaux_cobol.analyse_niveaux_cobol(
                dd_csv_path=dict_csv,
                out_csv_path=out_csv,
            )
            nb_lvl += 1
        except Exception as e:
            logger.exception("  Erreur niveaux %s : %s", prog, e)

    logger.info("  %d fichier(s) anomalies niveaux généré(s)", nb_lvl)


    # 14) Niveau 2.1 – Concepts de données (pivot transverse)
    logger.info("Étape 14/16 – Analyse des concepts de données (data_concepts_usage)")

    # Où trouver les règles (fichier CSV versionné dans le repo)
    
    rules_csv = Path(config.get("data_concepts_rules_csv", "config/niveau2/data_concepts_rules.csv")).resolve()

    concepts_dir = csv_dir / "data_concepts"
    concepts_dir.mkdir(parents=True, exist_ok=True)

    out_csv = concepts_dir / "data_concepts_usage.csv"

    try:
        data_concepts_usage.build_data_concepts_usage(
            dd_global_csv=data_dict_global,
            usage_csv_dir=csv_dir,
            rules_csv=rules_csv,
            out_csv=out_csv,
        )
        logger.info("  data_concepts_usage : %s", out_csv)
        logger.info("  data_concepts_rules : %s", rules_csv)
    except Exception as e:
        logger.exception("  Erreur data_concepts_usage : %s", e)

    # 15) Niveau 2.2 – Cartographie des structures de données (structures_cartography)
    logger.info("Étape 15/16 – Cartographie des structures de données (structures_cartography)")

    structures_dir = csv_dir / "structures_cartography"
    structures_dir.mkdir(parents=True, exist_ok=True)

    out_csv = structures_dir / "structures_cartography.csv"

    try:
        structures_cartography.build_structures_cartography(
            dd_global_csv=data_dict_global,
            usage_csv_dir=csv_dir,
            rules_csv=rules_csv,
            out_csv=out_csv,
        )
        logger.info("  structures_cartography : %s", out_csv)
    except Exception as e:
        logger.exception("  Erreur structures_cartography : %s", e)



    # 16) Niveau 2.C – Consolidation des concepts (concepts_consolidation)
    logger.info("Étape 16/16 – Consolidation des concepts (concepts_consolidation)")

    consolidation_dir = csv_dir / "concepts_consolidation"
    consolidation_dir.mkdir(parents=True, exist_ok=True)

    try:
        generated = concepts_consolidation.build_concepts_consolidation(
            structures_cartography_csv=out_csv,
            out_dir=consolidation_dir,
            top_n=int(config.get("concepts_top_n", 25) or 25),
        )
        logger.info("  concepts_summary           : %s", generated.get("concepts_summary"))
        logger.info("  concepts_by_program        : %s", generated.get("concepts_by_program"))
        logger.info("  top_transversal_structures : %s", generated.get("top_transversal_structures"))
    except Exception as e:
        logger.exception("  Erreur concepts_consolidation : %s", e)

    # n) Étape n : réservées pour futures branches (graphes, synthèse globale...)
    logger.info("Pipeline terminé ✅")

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
