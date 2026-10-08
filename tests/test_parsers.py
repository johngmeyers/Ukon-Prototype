import json
from datetime import date
from pathlib import Path

import pytest

from coverage_readiness.parsers import EvidenceParseError
from coverage_readiness.parsers.edr import parse_edr_inventory
from coverage_readiness.parsers.m365 import parse_m365_mfa
from coverage_readiness.parsers.patches import parse_patches
from coverage_readiness.schema import ControlId

BUSINESSES = Path(__file__).parent.parent / "fixtures" / "businesses"
AS_OF = date(2026, 9, 30)


def by_control(evidence):
    return {e.control_id: e for e in evidence}


# --- M365 MFA ---------------------------------------------------------------


@pytest.mark.parametrize(
    "business, accounts",
    [("acme_dental", 14), ("birch_logistics", 32), ("cedar_law", 20)],
)
def test_m365_fixtures_show_mfa_enforced_everywhere(business, accounts):
    found = by_control(parse_m365_mfa(BUSINESSES / business / "m365_mfa.csv"))
    assert set(found) == {ControlId.MFA_EMAIL, ControlId.MFA_PRIVILEGED}
    email = found[ControlId.MFA_EMAIL]
    assert email.value is True
    assert email.detail == f"MFA enforced for {accounts} of {accounts} accounts"
    assert found[ControlId.MFA_PRIVILEGED].value is True
    assert found[ControlId.MFA_PRIVILEGED].detail == "MFA enforced for 2 of 2 admin accounts"
    assert found[ControlId.MFA_EMAIL].source == "m365_mfa.csv"


def test_m365_admin_without_mfa_fails_both_controls(tmp_path):
    path = tmp_path / "m365_mfa.csv"
    path.write_text(
        "UserPrincipalName,DisplayName,IsAdmin,MFAStatus,DefaultMethod\n"
        "ana@x.example,Ana,False,Enforced,PhoneAppOTP\n"
        "admin@x.example,Admin,True,Enabled,\n"
    )
    found = by_control(parse_m365_mfa(path))
    assert found[ControlId.MFA_EMAIL].value is False
    assert found[ControlId.MFA_PRIVILEGED].value is False
    assert found[ControlId.MFA_PRIVILEGED].detail == (
        "MFA enforced for 0 of 1 admin accounts; not enforced: admin@x.example"
    )


def test_m365_with_no_admins_reports_unknown_privileged(tmp_path):
    path = tmp_path / "m365_mfa.csv"
    path.write_text("UserPrincipalName,IsAdmin,MFAStatus\nana@x.example,False,Enforced\n")
    found = by_control(parse_m365_mfa(path))
    assert found[ControlId.MFA_PRIVILEGED].value is None


@pytest.mark.parametrize(
    "content, message",
    [
        ("UserPrincipalName,MFAStatus\nana@x.example,Enforced\n", "missing columns: IsAdmin"),
        ("UserPrincipalName,IsAdmin,MFAStatus\n", "no data rows"),
        ("UserPrincipalName,IsAdmin,MFAStatus\nana@x.example,False,Maybe\n", "line 2"),
    ],
)
def test_m365_malformed_raises_clear_error(tmp_path, content, message):
    path = tmp_path / "m365_mfa.csv"
    path.write_text(content)
    with pytest.raises(EvidenceParseError, match=message) as exc:
        parse_m365_mfa(path)
    assert str(exc.value).startswith("m365_mfa.csv: ")


# --- EDR inventory ----------------------------------------------------------


def test_edr_birch_shows_47_of_50():
    [evidence] = parse_edr_inventory(BUSINESSES / "birch_logistics" / "edr_inventory.json")
    assert evidence.control_id == ControlId.EDR_ALL_ENDPOINTS
    assert evidence.value == pytest.approx(0.94)
    assert evidence.detail.startswith("CrowdStrike Falcon active on 47 of 50 devices (94%)")
    for host in ("BIRCH-WS17", "BIRCH-WS33", "BIRCH-WS41"):
        assert host in evidence.detail


@pytest.mark.parametrize("business, devices", [("acme_dental", 14), ("cedar_law", 22)])
def test_edr_full_coverage(business, devices):
    [evidence] = parse_edr_inventory(BUSINESSES / business / "edr_inventory.json")
    assert evidence.value == 1.0
    assert f"active on {devices} of {devices} devices (100%)" in evidence.detail
    assert "gaps" not in evidence.detail


@pytest.mark.parametrize(
    "content, message",
    [
        ("{not json", "invalid JSON at line 1"),
        (json.dumps({"vendor": "X"}), "non-empty 'devices' list"),
        (json.dumps({"devices": []}), "non-empty 'devices' list"),
        (json.dumps({"devices": [{"hostname": "WS01"}]}), "device 0: missing"),
    ],
)
def test_edr_malformed_raises_clear_error(tmp_path, content, message):
    path = tmp_path / "edr_inventory.json"
    path.write_text(content)
    with pytest.raises(EvidenceParseError, match=message):
        parse_edr_inventory(path)


def test_missing_file_raises_clear_error(tmp_path):
    with pytest.raises(EvidenceParseError, match="edr_inventory.json: cannot read file"):
        parse_edr_inventory(tmp_path / "edr_inventory.json")


# --- Patches ----------------------------------------------------------------


@pytest.mark.parametrize(
    "business, slowest_days, slowest_id, critical_count",
    [
        ("acme_dental", 9, "ADB-24-29", 7),
        ("birch_logistics", 21, "KB5041580", 6),
        ("cedar_law", 12, "KB5041580", 6),
    ],
)
def test_patches_fixtures_report_slowest_critical(
    business, slowest_days, slowest_id, critical_count
):
    [evidence] = parse_patches(BUSINESSES / business / "patches.csv", as_of=AS_OF)
    assert evidence.control_id == ControlId.CRITICAL_PATCH_DAYS
    assert evidence.value == slowest_days
    assert evidence.detail == (
        f"Slowest critical patch took {slowest_days} days ({slowest_id}); "
        f"{critical_count} critical patches in report"
    )


def test_patches_ignore_non_critical_and_count_pending_against_as_of(tmp_path):
    path = tmp_path / "patches.csv"
    path.write_text(
        "patch_id,product,severity,released,deployed\n"
        "KB1,Windows,Important,2026-01-01,2026-06-01\n"
        "KB2,Windows,Critical,2026-09-01,2026-09-05\n"
        "KB3,Windows,Critical,2026-09-10,\n"
    )
    [evidence] = parse_patches(path, as_of=AS_OF)
    assert evidence.value == 20
    assert "not yet deployed as of 2026-09-30: KB3" in evidence.detail


def test_patches_with_no_critical_rows_reports_unknown(tmp_path):
    path = tmp_path / "patches.csv"
    path.write_text("patch_id,severity,released,deployed\nKB1,Moderate,2026-01-01,2026-01-09\n")
    [evidence] = parse_patches(path, as_of=AS_OF)
    assert evidence.value is None


@pytest.mark.parametrize(
    "row, message",
    [
        ("KB1,Critical,09/01/2026,2026-09-05", "line 2: bad date"),
        ("KB1,Critical,2026-09-05,2026-09-01", "line 2: KB1 deployed before release"),
    ],
)
def test_patches_malformed_raises_clear_error(tmp_path, row, message):
    path = tmp_path / "patches.csv"
    path.write_text(f"patch_id,severity,released,deployed\n{row}\n")
    with pytest.raises(EvidenceParseError, match=message):
        parse_patches(path, as_of=AS_OF)
