import re
import csv
from pathlib import Path
from typing import List, Dict, Optional

WRITE_PATTERNS = [
    r"\bMOVE\s+.+\s+TO\s+{var}\b",
    r"\bADD\s+.+\s+TO\s+{var}\b",
    r"\bSUBTRACT\s+.+\s+FROM\s+{var}\b",
    r"\bINITIALIZE\s+{var}\b",
    r"\bSTRING\s+.+\s+INTO\s+{var}\b",
    r"\bUNSTRING\s+.+\s+INTO\s+{var}\b",
    r"\bCOMPUTE\s+{var}\s*=",
]

READ_PATTERNS = [
    r"\bIF\s+{var}\b",
    r"\bEVALUATE\s+{var}\b",
    r"\bPERFORM\s+.+\s+UNTIL\s+{var}\b",
    r"\bDISPLAY\s+{var}\b",
    r"\bMOVE\s+{var}\s+TO\b",
    r"\bADD\s+{var}\s+TO\b",
    r"\bSUBTRACT\s+{var}\s+FROM\b",
    r"\bCOMPUTE\s+.+\s*=\s*.*\b{var}\b",
]


def _load_dd_for_program(dd_by_program_dir: Path, program: str) -> List[Dict[str, str]]:
    program_u = program.strip().upper()
    dd_path = dd_by_program_dir / f"{program_u}_dd.csv"
    if not dd_path.exists():
        raise FileNotFoundError(f"DD par programme manquant: {dd_path}")

    variables: List[Dict[str, str]] = []
    with dd_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("name") or "").strip()
            if not name:
                continue
            full_path = (row.get("full_path") or "").strip()
            var_id = full_path if full_path else name
            variables.append({"id": var_id, "token": name.upper()})

    return variables


def _load_proc_ranges(program_structure_csv: Path, program: str) -> List[Dict[str, object]]:
    program_u = program.strip().upper()
    ranges: List[Dict[str, object]] = []

    with program_structure_csv.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            prog = (row.get("programme") or "").strip().upper()
            if prog != program_u:
                continue

            proc = (row.get("proc") or "").strip()
            deb = (row.get("deb_proc") or "").strip()
            fin = (row.get("fin_proc") or "").strip()

            if not proc or not deb.isdigit() or not fin.isdigit():
                continue

            ranges.append({"start": int(deb), "end": int(fin), "paragraph": proc})

    ranges.sort(key=lambda r: int(r["start"]))
    return ranges


def _find_paragraph_for_seq(seq: int, ranges: List[Dict[str, object]]) -> str:
    for r in ranges:
        if int(r["start"]) <= seq <= int(r["end"]):
            return str(r["paragraph"])
    return "?"


def _classify_usage(var_token: str, code_upper: str) -> Optional[str]:
    for pattern in WRITE_PATTERNS:
        if re.search(pattern.format(var=re.escape(var_token)), code_upper):
            return "write"
    for pattern in READ_PATTERNS:
        if re.search(pattern.format(var=re.escape(var_token)), code_upper):
            return "read"
    return None


def scan_variable_usage_for_program(
    *,
    program: str,
    etude_path: Path,
    dd_by_program_dir: Path,
    program_structure_csv: Path,
) -> List[Dict[str, str]]:
    """
    Analyse un .etude et produit une liste d'usages.
    - Affectation paragraphe via program_structure.csv (deb_proc..fin_proc)
    - Zone code: col 8-72 (index 7:72)
    """
    program_u = program.strip().upper()

    if not etude_path.exists():
        raise FileNotFoundError(f".etude manquant: {etude_path}")
    if not dd_by_program_dir.exists():
        raise FileNotFoundError(f"dd_by_program_dir manquant: {dd_by_program_dir}")
    if not program_structure_csv.exists():
        raise FileNotFoundError(f"program_structure.csv manquant: {program_structure_csv}")

    variables = _load_dd_for_program(dd_by_program_dir, program_u)
    ranges = _load_proc_ranges(program_structure_csv, program_u)

    usages: List[Dict[str, str]] = []

    with etude_path.open(encoding="latin-1", errors="ignore") as f:
        for line in f:
            seq_stripped = line[0:6].strip()
            code_upper = line[7:72].upper()

            paragraph = "?"
            if seq_stripped.isdigit():
                paragraph = _find_paragraph_for_seq(int(seq_stripped), ranges)

            for var in variables:
                tok = var["token"]
                if tok not in code_upper:
                    continue

                usage_type = _classify_usage(tok, code_upper)

                # Fallback minimal: token présent dans un paragraphe connu => read
                if not usage_type and paragraph != "?":
                    usage_type = "read"

                if not usage_type:
                    continue

                usages.append(
                    {
                        "program": program_u,
                        "variable": var["id"],
                        "usage_type": usage_type,
                        "paragraph": paragraph,
                        "line_etude": seq_stripped,
                        "context_usage_final": line.rstrip("\n"),
                    }
                )

    return usages


def write_usage_csv(program: str, rows: List[Dict[str, str]], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{program.strip().upper()}_usage.csv"
    fieldnames = ["program", "variable", "usage_type", "paragraph", "line_etude", "context_usage_final"]

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)

    return out_path


def scan_variable_usage(
    *,
    normalized_files: List[str],
    work_dir: str,
    dd_by_program_dir: str,
    program_structure_csv: str,
) -> List[Path]:
    """
    API pipeline: boucle sur les .etude normalisés et génère les CSV usages dans <work_dir>/csv.
    Retourne la liste des chemins générés.
    """
    work = Path(work_dir).resolve()
    out_dir = work / "csv"
    dd_dir = Path(dd_by_program_dir).resolve()
    ps_csv = Path(program_structure_csv).resolve()

    outputs: List[Path] = []

    for p in normalized_files:
        etude_path = Path(p)
        program = etude_path.name.split(".")[0].strip().upper()
        if not program:
            continue

        rows = scan_variable_usage_for_program(
            program=program,
            etude_path=etude_path,
            dd_by_program_dir=dd_dir,
            program_structure_csv=ps_csv,
        )
        outputs.append(write_usage_csv(program, rows, out_dir))

    return outputs


# CLI conservée (utile pour test ponctuel)
def main():
    import argparse

    parser = argparse.ArgumentParser(description="Scan usages variables (dd_by_program + program_structure.csv).")
    parser.add_argument("program", help="Nom programme (ex: SRSRA130)")
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--dd-by-program-dir", required=True)
    parser.add_argument("--program-structure-csv", required=True)
    parser.add_argument("--etude-path", default=None, help="Optionnel: chemin .etude (sinon <work_dir>/etude/<pgm>.cbl.etude)")
    args = parser.parse_args()

    program = args.program.strip().upper()
    work = Path(args.work_dir).resolve()

    etude_path = Path(args.etude_path).resolve() if args.etude_path else (work / "etude" / f"{program}.cbl.etude")

    rows = scan_variable_usage_for_program(
        program=program,
        etude_path=etude_path,
        dd_by_program_dir=Path(args.dd_by_program_dir),
        program_structure_csv=Path(args.program_structure_csv),
    )

    out = write_usage_csv(program, rows, work / "csv")
    print(f"[OK] {out}")


if __name__ == "__main__":
    main()
