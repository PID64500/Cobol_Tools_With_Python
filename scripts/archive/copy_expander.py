"""
copy_expander.py

Expansion des COPY COBOL avec gestion de:
- COPY simples
- COPY ... REPLACING ==...== BY ==...== (plusieurs paires possibles)
- Pseudo-text du type ==:DEPENDING ON FUTIL-NBGR:==, traité textuellement.

Interface principale utilisée par le pipeline :
    expand_copybooks(lines, copybooks_dir) -> nouvelles lignes avec COPY développés.

Règles supplémentaires:
- Toute COPY dont le nom de copybook commence par 'SMASH' est ignorée (debugger).
- Dans les copybooks normaux, toute ligne dont le texte commence par 'SMASH'
  (après trim à gauche) est ignorée.
- Fallback : après REPLACING, on supprime toute séquence de la forme
  ':DEPENDING ON XXX:' encore présente dans le texte.
"""

from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Set, Tuple, Union

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pseudo-text & REPLACING
# ---------------------------------------------------------------------------

def _normalize_pseudotext(text: str) -> str:
    """
    Normalise le pseudo-text inclus entre == ==.

    Version simple : on renvoie tel quel, pour matcher exactement ce
    qui est dans le source, y compris les ':'.
    Ex: ==:DEPENDING ON FUTIL-NBGR:== -> ':DEPENDING ON FUTIL-NBGR:'
    """
    return text


_PSEUDOTEXT_PAIR_RE = re.compile(
    r"==(?P<old>.*?)==\s+BY\s+==(?P<new>.*?)==",
    re.IGNORECASE | re.DOTALL,
)


def extract_replacing_pairs(copy_statement: str) -> List[Tuple[str, str]]:
    """
    Extrait les paires (ancien, nouveau) d'une clause COPY ... REPLACING.

    On cherche:
        REPLACING ==old1== BY ==new1== ==old2== BY ==new2== ...
    """
    upper_stmt = copy_statement.upper()
    idx = upper_stmt.find("REPLACING")
    if idx == -1:
        return []

    tail = copy_statement[idx + len("REPLACING") :]

    pairs: List[Tuple[str, str]] = []
    pos = 0
    while True:
        m = _PSEUDOTEXT_PAIR_RE.search(tail, pos)
        if not m:
            break

        old_raw = m.group("old")
        new_raw = m.group("new")

        old_norm = _normalize_pseudotext(old_raw)
        new_norm = _normalize_pseudotext(new_raw)

        pairs.append((old_norm, new_norm))
        pos = m.end()

    return pairs


def apply_replacing(text: str, pairs: Sequence[Tuple[str, str]]) -> str:
    """
    Applique les paires REPLACING sur le texte du COPY.

    + Fallback : si malgré tout il reste des bouts ':DEPENDING ON XXX:'
      on les supprime complètement, ce qui est équivalent à 'BY == ==.'
      (on enlève la clause DEPENDING ON).
    """
    # 1) REPLACING classique
    for old, new in pairs:
        if not old:
            continue
        text = text.replace(old, new)

    # 2) Fallback générique pour :DEPENDING ON XXX:
    #    Exemple typique : ':DEPENDING ON FUTIL-NBGR:'
    text = re.sub(r":DEPENDING ON [A-Z0-9\-]+:", " ", text)

    return text


# ---------------------------------------------------------------------------
# Parsing COPY
# ---------------------------------------------------------------------------

_COPY_WORD_RE = re.compile(r"\bCOPY\b", re.IGNORECASE)


def _is_comment_line(line: str) -> bool:
    stripped = line.lstrip()
    if not stripped:
        return False
    return stripped[0] == "*"


def _collect_copy_statement(lines: Sequence[str], start_index: int) -> Tuple[List[str], int]:
    """
    À partir d'un index où 'COPY' a été repéré dans la ligne,
    agrège les lignes jusqu'au '.' final de l'instruction COPY.
    """
    collected: List[str] = []
    i = start_index
    while i < len(lines):
        line = lines[i]
        collected.append(line)
        if "." in line:
            i += 1
            break
        i += 1
    return collected, i


def _extract_copybook_name(copy_stmt: str) -> Optional[str]:
    """
    Extrait le nom de copybook à partir d'une instruction COPY complète.

    Gère les formes:
      COPY NOM.
      COPY NOM REPLACING ...
      COPY NOM IN LIB.
      COPY NOM OF LIB.
    """
    tokens = copy_stmt.strip().split()
    if not tokens:
        return None

    try:
        idx = next(i for i, t in enumerate(tokens) if t.upper() == "COPY")
    except StopIteration:
        return None

    if idx + 1 >= len(tokens):
        return None

    candidate = tokens[idx + 1]

    # COPY IN / OF library
    if candidate.upper() in {"IN", "OF"} and idx + 2 < len(tokens):
        candidate = tokens[idx + 2]

    candidate = candidate.rstrip(".")
    return candidate or None


# ---------------------------------------------------------------------------
# Chargement copybooks (avec nettoyage SMASH)
# ---------------------------------------------------------------------------

def _load_copybook_text_from_dirs(copybook_name: str, copybook_dirs: Sequence[Path]) -> Optional[str]:
    """
    Charge le contenu texte d'un copybook en parcourant une liste de répertoires.

    Pour les copybooks normaux:
      - Toute ligne dont le texte, après strip à gauche, commence par 'SMASH'
        est ignorée (lignes injectées par un debugger).

    On teste les extensions usuelles .cpy/.cbl/.cob.
    """
    candidates = [
        copybook_name,
        f"{copybook_name}.cpy",
        f"{copybook_name}.CPY",
        f"{copybook_name}.cbl",
        f"{copybook_name}.CBL",
        f"{copybook_name}.cob",
        f"{copybook_name}.COB",
    ]

    for directory in copybook_dirs:
        for cand in candidates:
            path = directory / cand
            if path.is_file():
                try:
                    raw_text = path.read_text(encoding="latin-1", errors="ignore")
                except Exception as exc:  # pragma: no cover
                    logger.error("Erreur de lecture copybook %s: %s", path, exc)
                    return None

                filtered_lines = [
                    l for l in raw_text.splitlines(keepends=True)
                    if not l.lstrip().startswith("SMASH")
                ]
                text = "".join(filtered_lines)
                return text

    logger.warning("Copybook introuvable: %s (dirs=%s)", copybook_name, [str(d) for d in copybook_dirs])
    return None


# ---------------------------------------------------------------------------
# Expansion récursive d'un TEXTE COBOL
# ---------------------------------------------------------------------------

def expand_copies_in_text(
    text: str,
    copybook_dirs: Sequence[Path],
    seen_copybooks: Optional[Set[str]] = None,
    context: str = "",
) -> str:
    """
    Développe récursivement les COPY présents dans un texte COBOL.

    - text          : contenu COBOL (programme ou copybook)
    - copybook_dirs : liste de répertoires où chercher les copybooks
    - seen_copybooks : ensemble des copybooks déjà vus (anti-boucle)
    - context       : texte de contexte pour les logs
    """
    if seen_copybooks is None:
        seen_copybooks = set()

    lines = text.splitlines(keepends=True)
    out_lines: List[str] = []

    i = 0
    while i < len(lines):
        line = lines[i]

        # On ignore les commentaires pour la détection du mot COPY
        if _is_comment_line(line) or not _COPY_WORD_RE.search(line):
            out_lines.append(line)
            i += 1
            continue

        # On a un "COPY" dans la ligne → on reconstruit l'instruction complète
        stmt_lines, next_i = _collect_copy_statement(lines, i)
        stmt_text = " ".join(l.rstrip("\n").rstrip() for l in stmt_lines)

        if not _COPY_WORD_RE.search(stmt_text):
            out_lines.extend(stmt_lines)
            i = next_i
            continue

        copybook_name = _extract_copybook_name(stmt_text)
        if not copybook_name:
            out_lines.extend(stmt_lines)
            i = next_i
            continue

        # 🔹 Règle: les copybooks SMASH* sont ignorés entièrement (debugger)
        if copybook_name.upper().startswith("SMASH"):
            logger.debug("COPY %s ignoré (copybook de debugger SMASH)", copybook_name)
            i = next_i
            continue

        logger.debug("Expansion COPY %s (context=%s)", copybook_name, context)

        if copybook_name in seen_copybooks:
            logger.warning(
                "Boucle de COPY détectée pour %s (context=%s). COPY laissé tel quel.",
                copybook_name,
                context,
            )
            out_lines.extend(stmt_lines)
            i = next_i
            continue

        copy_text = _load_copybook_text_from_dirs(copybook_name, copybook_dirs)
        if copy_text is None:
            out_lines.extend(stmt_lines)
            i = next_i
            continue

        # Expansion récursive du copybook
        new_seen = set(seen_copybooks)
        new_seen.add(copybook_name)
        expanded_copy = expand_copies_in_text(
            copy_text,
            copybook_dirs=copybook_dirs,
            seen_copybooks=new_seen,
            context=f"{context}->{copybook_name}" if context else copybook_name,
        )

        # Clause REPLACING éventuelle
        pairs = extract_replacing_pairs(stmt_text)
        if pairs:
            logger.debug(
                "COPY %s avec REPLACING, paires=%s (context=%s)",
                copybook_name,
                pairs,
                context,
            )
            expanded_copy = apply_replacing(expanded_copy, pairs)

        # Sentinelles sans toucher aux colonnes
        sentinel_start = f"      *COPYBOOK {copybook_name}\n"
        sentinel_end = f"      *END COPYBOOK {copybook_name}\n"

        out_lines.append(sentinel_start)
        for raw_line in expanded_copy.splitlines(keepends=False):
            out_lines.append(raw_line + "\n")
        out_lines.append(sentinel_end)

        i = next_i

    return "".join(out_lines)


# ---------------------------------------------------------------------------
# API "lignes en mémoire" pour normalize_file.py
# ---------------------------------------------------------------------------

def expand_copybooks(
    lines: Sequence[str],
    copybooks_dir: Optional[Union[str, Path]],
) -> List[str]:
    """
    Développe les COPY sur une liste de lignes COBOL déjà lues.

    Utilisation typique dans normalize_file.py :
        lines = fin.readlines()
        lines = expand_copybooks(lines, copybooks_dir)
    """
    if not copybooks_dir:
        return list(lines)

    text = "".join(lines)
    copy_dirs = [Path(copybooks_dir)]

    expanded = expand_copies_in_text(
        text,
        copybook_dirs=copy_dirs,
        seen_copybooks=set(),
        context="normalize_file",
    )

    return expanded.splitlines(keepends=True)


# ---------------------------------------------------------------------------
# Fonctions annexes fichiers / répertoires (optionnelles)
# ---------------------------------------------------------------------------

def expand_copies_in_file(
    source_path: Path,
    copybook_dirs: Sequence[Path],
) -> str:
    text = source_path.read_text(encoding="latin-1", errors="ignore")
    return expand_copies_in_text(
        text,
        copybook_dirs=copybook_dirs,
        seen_copybooks=set(),
        context=str(source_path),
    )


def expand_copies_in_directory(
    source_dir: Path,
    copybook_dirs: Sequence[Path],
    output_dir: Optional[Path] = None,
    patterns: Iterable[str] = (".cbl", ".CBL", ".cob", ".COB", ".etude"),
) -> None:
    source_dir = source_dir.resolve()
    if output_dir is None:
        output_dir = source_dir
    else:
        output_dir = output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

    patterns = tuple(patterns)

    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix not in patterns:
            continue

        rel = path.relative_to(source_dir)
        dest = output_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)

        logger.info("Expansion COPY: %s -> %s", path, dest)

        new_text = expand_copies_in_file(path, copybook_dirs=copybook_dirs)
        dest.write_text(new_text, encoding="latin-1", errors="ignore")


def expand_copies(config: dict) -> None:
    copybook_dirs_cfg = config.get("copybook_dirs")
    if not copybook_dirs_cfg:
        raise ValueError("Config: 'copybook_dirs' est obligatoire pour expand_copies")

    copybook_dirs = [Path(p) for p in copybook_dirs_cfg]

    work_dir = Path(config.get("work_dir", ".")).resolve()
    normalized_dir = config.get("normalized_dir")
    copy_expanded_dir = config.get("copy_expanded_dir")

    if normalized_dir:
        source_dir = Path(normalized_dir)
        if not source_dir.is_absolute():
            source_dir = work_dir / source_dir
    else:
        src_cfg = config.get("source_dir", work_dir)
        source_dir = Path(src_cfg)
        if not source_dir.is_absolute():
            source_dir = work_dir / source_dir

    if copy_expanded_dir:
        output_dir = Path(copy_expanded_dir)
        if not output_dir.is_absolute():
            output_dir = work_dir / copy_expanded_dir
    else:
        output_dir = source_dir

    logger.info(
        "Lancement expansion COPY: source_dir=%s, output_dir=%s, copybook_dirs=%s",
        source_dir,
        output_dir,
        copybook_dirs,
    )

    expand_copies_in_directory(
        source_dir=source_dir,
        copybook_dirs=copybook_dirs,
        output_dir=output_dir,
    )


# ---------------------------------------------------------------------------
# CLI optionnelle
# ---------------------------------------------------------------------------

def _setup_basic_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def cli(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Expansion des COPY COBOL.")
    parser.add_argument(
        "--source-dir",
        required=True,
        help="Répertoire contenant les sources COBOL à traiter",
    )
    parser.add_argument(
        "--copybook-dir",
        action="append",
        required=True,
        help="Répertoire de copybooks (répéter l'option si plusieurs)",
    )
    parser.add_argument(
        "--output-dir",
        help="Répertoire de sortie (par défaut: écrase dans source-dir)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Niveau de log (DEBUG, INFO, WARNING, ERROR)",
    )

    args = parser.parse_args(argv)
    _setup_basic_logging(args.log_level)

    source_dir = Path(args.source_dir)
    copybook_dirs = [Path(p) for p in args.copybook_dir]
    output_dir = Path(args.output_dir) if args.output_dir else None

    expand_copies_in_directory(
        source_dir=source_dir,
        copybook_dirs=copybook_dirs,
        output_dir=output_dir,
    )

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(cli())
