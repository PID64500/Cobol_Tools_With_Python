#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
copy_expander.py
----------------
Expansion des COPYBOOK dans un source COBOL.

But :
- Remplacer les lignes "COPY Xxxx." par le contenu du copybook correspondant
- Encadrer l'inclusion avec des sentinelles :
    *COPYBOOK <NAME>
    ...
    *END COPYBOOK <NAME>

Hypothèses :
- copybooks_dir contient des fichiers de copybook (extensions possibles: .cpy, .cob, .txt, sans extension)
- Encodage "latin-1" par défaut, errors="ignore"
- Expansion récursive possible (COPY dans COPY), avec protection anti-boucle
"""

import re
from pathlib import Path
from typing import List, Optional, Sequence, Union, Set


RE_COPY = re.compile(r"^\s*COPY\s+([A-Z0-9\-]+)\s*\.\s*$", re.IGNORECASE)

# Extensions candidates (ajuste si besoin)
COPY_EXTS = ["", ".cpy", ".CPY", ".cob", ".COB", ".txt", ".TXT"]


def _sentinel_start(copyname: str) -> str:
    return f"      *COPYBOOK {copyname}\n"


def _sentinel_end(copyname: str) -> str:
    return f"      *END COPYBOOK {copyname}\n"


def _find_copy_file(copyname: str, copybooks_dir: Union[str, Path]) -> Optional[Path]:
    base = Path(copybooks_dir)
    for ext in COPY_EXTS:
        p = base / f"{copyname}{ext}"
        if p.exists() and p.is_file():
            return p
    return None


def _read_copy_lines(path: Path, encoding: str = "latin-1") -> List[str]:
    return path.read_text(encoding=encoding, errors="ignore").splitlines(keepends=True)


def expand_copybooks(
    lines: Sequence[str],
    copybooks_dir: Optional[Union[str, Path]],
    encoding: str = "latin-1",
    _stack: Optional[Set[str]] = None,
) -> List[str]:
    """
    Expanse les COPYBOOK dans une liste de lignes COBOL.
    Retourne une nouvelle liste de lignes.
    """
    if not copybooks_dir:
        return list(lines)

    if _stack is None:
        _stack = set()

    out: List[str] = []

    for raw in lines:
        m = RE_COPY.match(raw.strip())
        if not m:
            out.append(raw if raw.endswith("\n") else raw + "\n")
            continue

        copyname = m.group(1).upper()

        # Anti-boucle récursive
        if copyname in _stack:
            # On laisse la ligne COPY telle quelle si boucle détectée
            out.append(raw if raw.endswith("\n") else raw + "\n")
            continue

        copy_path = _find_copy_file(copyname, copybooks_dir)
        if not copy_path:
            # Copybook introuvable -> on laisse la ligne COPY
            out.append(raw if raw.endswith("\n") else raw + "\n")
            continue

        out.append(_sentinel_start(copyname))

        _stack.add(copyname)
        copy_lines = _read_copy_lines(copy_path, encoding=encoding)
        # Expansion récursive des COPY dans le copybook lui-même
        expanded = expand_copybooks(copy_lines, copybooks_dir, encoding=encoding, _stack=_stack)
        out.extend(expanded)
        _stack.remove(copyname)

        out.append(_sentinel_end(copyname))

    return out
