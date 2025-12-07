"""
analysis_core_wrapper.py
------------------------

Adapter analysis_core.analyze_program() au pipeline V1.1.

Le pipeline attend :
    run_analysis(normalized_files, paragraphs_info, interactions_by_prog, callers_info, config)

Ton analyse existante utilise :
    analyze_program(etude_path)

Cette couche permet de :
    - ne RIEN casser dans analysis_core.py
    - garder run_pipeline() intact
    - agréger les résultats programme par programme
"""

from __future__ import annotations
from typing import Dict, Any, Iterable
import logging
from pathlib import Path

import analysis_core   # ton fichier original

logger = logging.getLogger(__name__)


def run_analysis(
    normalized_files: Iterable[str],
    paragraphs_info: Dict[str, Any],
    interactions_by_prog: Dict[str, Any],
    callers_info: Dict[str, Any],
    config: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Appelle ton analysis_core.analyze_program() pour chaque fichier .cbl.etude
    et renvoie une structure compatible avec les étapes suivantes du pipeline.
    """

    results: Dict[str, Any] = {}

    for f in normalized_files:
        path = Path(f)
        program_name = path.stem.replace(".cbl", "").replace(".etude", "")

        try:
            analysis = analysis_core.analyze_program(str(path))
            logger.info("analysis_core : %s analysé (%d paragraphes, %d appels, %d exits)",
                        program_name,
                        analysis.stats["nb_paragraphs"],
                        analysis.stats["nb_calls_total"],
                        analysis.stats["nb_exit_events"])
            results[program_name] = {
                "analysis_core": analysis,                    # ton analyse d'origine
                "interactions": interactions_by_prog.get(program_name, []),
                "callers_v1": callers_info.get(program_name, {}),
                "paragraphs_v1": paragraphs_info.get(str(path), []),
            }

        except Exception as e:
            logger.error("Erreur analysis_core sur %s : %s", program_name, e)

    logger.info("analysis_core_wrapper : analyse terminée pour %d programmes", len(results))
    return results
