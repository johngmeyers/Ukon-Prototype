"""Patch summary (CSV) -> slowest observed days to deploy a critical patch."""

from datetime import date
from pathlib import Path

from coverage_readiness.parsers import EvidenceParseError, read_csv
from coverage_readiness.schema import ControlId, EvidencedControl

COLUMNS = ["patch_id", "severity", "released", "deployed"]


def parse_patches(path: Path, as_of: date) -> list[EvidencedControl]:
    """A critical patch not yet deployed counts as open for (as_of - released) days."""
    rows = read_csv(path, COLUMNS)
    days: dict[str, int] = {}
    pending: list[str] = []
    for line, row in enumerate(rows, start=2):
        if row["severity"].strip().lower() != "critical":
            continue
        patch_id = row["patch_id"].strip()
        try:
            released = date.fromisoformat(row["released"].strip())
            deployed_text = row["deployed"].strip()
            deployed = date.fromisoformat(deployed_text) if deployed_text else None
        except ValueError as e:
            raise EvidenceParseError(path, f"line {line}: bad date ({e})") from e
        if deployed is None:
            pending.append(patch_id)
        end = deployed or as_of
        if end < released:
            raise EvidenceParseError(path, f"line {line}: {patch_id} deployed before release")
        days[patch_id] = (end - released).days

    if not days:
        return [
            EvidencedControl(
                control_id=ControlId.CRITICAL_PATCH_DAYS,
                value=None,
                source=path.name,
                detail="No critical patches in report",
            )
        ]
    slowest = max(days, key=days.__getitem__)
    detail = (
        f"Slowest critical patch took {days[slowest]} days ({slowest}); "
        f"{len(days)} critical patches in report"
    )
    if pending:
        detail += f"; not yet deployed as of {as_of}: {', '.join(pending)}"
    return [
        EvidencedControl(
            control_id=ControlId.CRITICAL_PATCH_DAYS,
            value=days[slowest],
            source=path.name,
            detail=detail,
        )
    ]
