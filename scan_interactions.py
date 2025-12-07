"""
scan_interactions.py - Scan des interactions CICS dans les fichiers COBOL normalisés.

On travaille DIRECTEMENT sur les fichiers normalisés.

Interactions gérées :

- EXIT
    - EXEC CICS RETURN
    - EXEC CICS RETURN TRANSID(...)
    - EXEC CICS XCTL
    - GOBACK
    - STOP RUN

- UI_EXIT (sortie "écran")
    - EXEC CICS SEND MAP(...)
    - EXEC CICS SEND MAPSET(...)

- INPUT (entrée "écran")
    - EXEC CICS RECEIVE MAP(...)
    - EXEC CICS RECEIVE MAPSET(...)

- TRIGGER (déclenchement asynchrone)
    - EXEC CICS START TRANSID(...)

- CALL (appel boomerang)
    - EXEC CICS LINK PROGRAM(...)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Iterable, Any
import logging
import re


logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Modèle
# ─────────────────────────────────────────────────────────────

@dataclass
class InteractionPoint:
    program: str               # Nom du programme COBOL (PROGRAM-ID)
    source: str                # Chemin du fichier
    seq: int                   # Numéro de ligne
    category: str              # "EXIT" | "INPUT" | "UI_EXIT" | "TRIGGER" | "CALL"
    kind: str                  # "XCTL" | "RETURN" | "RETURN TRANSID" | "SEND MAP" | ...

    # Détails optionnels suivant le type d'interaction
    map_name: Optional[str] = None
    mapset_name: Optional[str] = None
    target_program: Optional[str] = None     # pour LINK PROGRAM(...)
    target_transid: Optional[str] = None     # pour START TRANSID(...)
    raw: str = ""                            # Ligne brute


# ─────────────────────────────────────────────────────────────
# Utilitaires
# ─────────────────────────────────────────────────────────────

def normalize_line(line: str) -> str:
    """
    Normalisation agressive :
    - upper()
    - tous les blocs d'espaces → un seul
    """
    return " ".join(line.upper().split())


# Patterns COBOL / CICS
RE_PROGRAM_ID = re.compile(
    r"\bPROGRAM-ID\.?\s+([A-Z0-9$@#_-]+)",
    re.IGNORECASE,
)

RE_XCTL = re.compile(r"\bEXEC\s+CICS\s+XCTL\b", re.IGNORECASE)

RE_RETURN_TRANSID = re.compile(
    r"\bEXEC\s+CICS\s+RETURN\s+TRANSID\s*\(\s*['\"]?([A-Z0-9$@#_-]+)['\"]?\s*\)",
    re.IGNORECASE,
)
RE_RETURN = re.compile(r"\bEXEC\s+CICS\s+RETURN\b", re.IGNORECASE)

RE_GOBACK = re.compile(r"\bGOBACK\b", re.IGNORECASE)
RE_STOP_RUN = re.compile(r"\bSTOP\s+RUN\b", re.IGNORECASE)

RE_SEND_MAPSET = re.compile(
    r"\bEXEC\s+CICS\s+SEND\s+MAPSET\s*\(\s*['\"]?([A-Z0-9$@#_-]+)['\"]?\s*\)",
    re.IGNORECASE,
)
RE_SEND_MAP = re.compile(
    r"\bEXEC\s+CICS\s+SEND\s+MAP\s*\(\s*['\"]?([A-Z0-9$@#_-]+)['\"]?\s*\)",
    re.IGNORECASE,
)

RE_RECV_MAPSET = re.compile(
    r"\bEXEC\s+CICS\s+RECEIVE\s+MAPSET\s*\(\s*['\"]?([A-Z0-9$@#_-]+)['\"]?\s*\)",
    re.IGNORECASE,
)
RE_RECV_MAP = re.compile(
    r"\bEXEC\s+CICS\s+RECEIVE\s+MAP\s*\(\s*['\"]?([A-Z0-9$@#_-]+)['\"]?\s*\)",
    re.IGNORECASE,
)

# START TRANSID (trigger)
RE_START_TRANSID = re.compile(
    r"\bEXEC\s+CICS\s+START\b.*\bTRANSID\s*\(\s*['\"]?([A-Z0-9$@#_-]+)['\"]?\s*\)",
    re.IGNORECASE,
)

# LINK PROGRAM (boomerang)
RE_LINK_PROGRAM = re.compile(
    r"\bEXEC\s+CICS\s+LINK\b.*\bPROGRAM\s*\(\s*['\"]?([A-Z0-9$@#_-]+)['\"]?\s*\)",
    re.IGNORECASE,
)


# ─────────────────────────────────────────────────────────────
# Détection sur une ligne
# ─────────────────────────────────────────────────────────────

def detect_interactions_in_line(
    seq: int,
    code_line: str,
    program: str,
    source: str,
) -> List[InteractionPoint]:
    pts: List[InteractionPoint] = []

    norm = normalize_line(code_line)

    # --- EXITs -------------------------------------------------------------

    # RETURN TRANSID d'abord (plus spécifique)
    if RE_RETURN_TRANSID.search(norm):
        m_rt = RE_RETURN_TRANSID.search(norm)
        target_tran = m_rt.group(1) if m_rt else None
        pts.append(
            InteractionPoint(
                program=program,
                source=source,
                seq=seq,
                category="EXIT",
                kind="RETURN TRANSID",
                target_transid=target_tran,
                raw=code_line,
            )
        )
    elif RE_RETURN.search(norm):
        pts.append(
            InteractionPoint(
                program=program,
                source=source,
                seq=seq,
                category="EXIT",
                kind="RETURN",
                raw=code_line,
            )
        )

    if RE_XCTL.search(norm):
        pts.append(
            InteractionPoint(
                program=program,
                source=source,
                seq=seq,
                category="EXIT",
                kind="XCTL",
                raw=code_line,
            )
        )

    if RE_GOBACK.search(norm):
        pts.append(
            InteractionPoint(
                program=program,
                source=source,
                seq=seq,
                category="EXIT",
                kind="GOBACK",
                raw=code_line,
            )
        )

    if RE_STOP_RUN.search(norm):
        pts.append(
            InteractionPoint(
                program=program,
                source=source,
                seq=seq,
                category="EXIT",
                kind="STOP RUN",
                raw=code_line,
            )
        )

    # --- UI_EXIT : SEND MAP / MAPSET --------------------------------------

    m_sms = RE_SEND_MAPSET.search(norm)
    m_sm = RE_SEND_MAP.search(norm)

    if m_sms or m_sm:
        pts.append(
            InteractionPoint(
                program=program,
                source=source,
                seq=seq,
                category="UI_EXIT",
                kind="SEND MAPSET/MAP",
                mapset_name=m_sms.group(1) if m_sms else None,
                map_name=m_sm.group(1) if m_sm else None,
                raw=code_line,
            )
        )

    # --- INPUT : RECEIVE MAP / MAPSET -------------------------------------

    m_rms = RE_RECV_MAPSET.search(norm)
    m_rm = RE_RECV_MAP.search(norm)

    if m_rms or m_rm:
        pts.append(
            InteractionPoint(
                program=program,
                source=source,
                seq=seq,
                category="INPUT",
                kind="RECEIVE MAPSET/MAP",
                mapset_name=m_rms.group(1) if m_rms else None,
                map_name=m_rm.group(1) if m_rm else None,
                raw=code_line,
            )
        )

    # --- TRIGGER : START TRANSID ------------------------------------------

    m_start = RE_START_TRANSID.search(norm)
    if m_start:
        transid = m_start.group(1)
        pts.append(
            InteractionPoint(
                program=program,
                source=source,
                seq=seq,
                category="TRIGGER",
                kind="START TRANSID",
                target_transid=transid,
                raw=code_line,
            )
        )

    # --- CALL : LINK PROGRAM ----------------------------------------------

    m_link = RE_LINK_PROGRAM.search(norm)
    if m_link:
        target_pgm = m_link.group(1)
        pts.append(
            InteractionPoint(
                program=program,
                source=source,
                seq=seq,
                category="CALL",
                kind="LINK",
                target_program=target_pgm,
                raw=code_line,
            )
        )

    return pts


# ─────────────────────────────────────────────────────────────
# Scan de fichiers
# ─────────────────────────────────────────────────────────────

def guess_program_name_from_lines(lines: Iterable[str], fallback: str) -> str:
    """
    Essaie de trouver PROGRAM-ID dans le fichier.
    Si non trouvé, on retourne le fallback (par ex. nom de fichier).
    """
    for line in lines:
        m = RE_PROGRAM_ID.search(line)
        if m:
            return m.group(1)
    return fallback


def scan_from_files(
    normalized_files: Iterable[str | Path],
    config: Dict[str, Any] | None = None,
) -> Dict[str, List[InteractionPoint]]:
    """
    Scan tous les fichiers COBOL normalisés pour y détecter les interactions.

    Retour :
        dict[program_name] -> list[InteractionPoint]
    """
    interactions_by_prog: Dict[str, List[InteractionPoint]] = {}

    for file_path in normalized_files:
        path = Path(file_path)
        source = str(path)

        try:
            with path.open("r", encoding="utf-8") as f:
                all_lines = f.readlines()
        except UnicodeDecodeError:
            with path.open("r", encoding="cp1252", errors="replace") as f:
                all_lines = f.readlines()
        except FileNotFoundError:
            logger.warning("scan_from_files : fichier introuvable %s", source)
            continue

        filename = path.name
        if ".cbl" in filename.lower():
            program_fallback = filename.split(".cbl")[0]
        else:
            program_fallback = path.stem

        program = guess_program_name_from_lines(all_lines, program_fallback)

        for idx, line in enumerate(all_lines, start=1):
            pts = detect_interactions_in_line(
                seq=idx,
                code_line=line.rstrip("\n"),
                program=program,
                source=source,
            )
            if pts:
                interactions_by_prog.setdefault(program, []).extend(pts)

    logger.info(
        "scan_from_files : détecté %d programme(s) avec interactions",
        len(interactions_by_prog),
    )
    return interactions_by_prog
