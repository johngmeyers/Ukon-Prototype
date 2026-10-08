"""Deterministic parsers for structured MSP evidence exports. No LLM calls."""

import csv
from pathlib import Path


class EvidenceParseError(ValueError):
    """An evidence file is missing, malformed or empty. The message names the file."""

    def __init__(self, path: Path, problem: str):
        super().__init__(f"{path.name}: {problem}")
        self.path = path


def read_csv(path: Path, required: list[str]) -> list[dict[str, str]]:
    """Read a CSV into dict rows, failing clearly on missing columns or no rows."""
    try:
        with path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            missing = [c for c in required if c not in (reader.fieldnames or [])]
            if missing:
                raise EvidenceParseError(path, f"missing columns: {', '.join(missing)}")
            rows = list(reader)
    except OSError as e:
        raise EvidenceParseError(path, f"cannot read file ({e.strerror})") from e
    if not rows:
        raise EvidenceParseError(path, "no data rows")
    return rows
