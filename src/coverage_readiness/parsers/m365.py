"""Microsoft 365 per-user MFA report (CSV) -> MFA on email and MFA on privileged accounts."""

from pathlib import Path

from coverage_readiness.parsers import EvidenceParseError, read_csv
from coverage_readiness.schema import ControlId, EvidencedControl

COLUMNS = ["UserPrincipalName", "IsAdmin", "MFAStatus"]
# Only "Enforced" means MFA is required at sign-in. "Enabled" is enrolled but not enforced.
MFA_STATUSES = {"Enforced": True, "Enabled": False, "Disabled": False}
BOOLS = {"True": True, "False": False}


def parse_m365_mfa(path: Path) -> list[EvidencedControl]:
    rows = read_csv(path, COLUMNS)
    accounts: list[tuple[str, bool, bool]] = []
    for line, row in enumerate(rows, start=2):
        is_admin = BOOLS.get(row["IsAdmin"].strip())
        enforced = MFA_STATUSES.get(row["MFAStatus"].strip())
        if is_admin is None or enforced is None:
            raise EvidenceParseError(
                path,
                f"line {line}: IsAdmin={row['IsAdmin']!r}, MFAStatus={row['MFAStatus']!r} "
                f"(expected IsAdmin in {sorted(BOOLS)}, MFAStatus in {sorted(MFA_STATUSES)})",
            )
        accounts.append((row["UserPrincipalName"].strip(), is_admin, enforced))

    admins = [a for a in accounts if a[1]]
    return [
        _summarize(ControlId.MFA_EMAIL, accounts, "accounts", path),
        _summarize(ControlId.MFA_PRIVILEGED, admins, "admin accounts", path),
    ]


def _summarize(
    control_id: ControlId, accounts: list[tuple[str, bool, bool]], noun: str, path: Path
) -> EvidencedControl:
    if not accounts:
        return EvidencedControl(
            control_id=control_id, value=None, source=path.name, detail=f"No {noun} in report"
        )
    without = [upn for upn, _, enforced in accounts if not enforced]
    detail = f"MFA enforced for {len(accounts) - len(without)} of {len(accounts)} {noun}"
    if without:
        detail += f"; not enforced: {', '.join(without)}"
    return EvidencedControl(
        control_id=control_id, value=not without, source=path.name, detail=detail
    )
