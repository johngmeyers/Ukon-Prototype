"""Claim vs. evidence comparison: the table of rules, written before the implementation.

Precedence, highest first:
  1. needs_review  claim missing, claim value null, or claim confidence < 0.8
  2. needs_review  any LLM-read evidence with confidence < 0.8
  3. unverifiable  control has no evidence source, or no usable evidence was found
  4. needs_review  evidence sources disagree with each other
  5. supported / contradicted  compare the claim to the evidence
"""

import pytest

from coverage_readiness.compare import compare_all, compare_control
from coverage_readiness.schema import ClaimedControl, ControlId, EvidencedControl, FindingStatus

MFA = ControlId.MFA_EMAIL
EDR = ControlId.EDR_ALL_ENDPOINTS
PATCH = ControlId.CRITICAL_PATCH_DAYS
RESTORE = ControlId.BACKUP_RESTORE_TESTED
TRAINING = ControlId.SECURITY_AWARENESS_TRAINING

SUPPORTED = FindingStatus.SUPPORTED
CONTRADICTED = FindingStatus.CONTRADICTED
UNVERIFIABLE = FindingStatus.UNVERIFIABLE
NEEDS_REVIEW = FindingStatus.NEEDS_REVIEW


def claim(control_id, value, confidence=0.95):
    return ClaimedControl(
        control_id=control_id,
        value=value,
        confidence=confidence,
        source_quote="quote",
        source_question_id="q1",
    )


def ev(control_id, value, source="export", confidence=None):
    return EvidencedControl(
        control_id=control_id,
        value=value,
        source=source,
        detail="detail",
        confidence=confidence,
    )


# (id, control, claim, evidence, expected status, text the note must contain or None)
# fmt: off
CASES = [
    # --- From the build plan -------------------------------------------------
    ("claim true, evidence true", MFA, claim(MFA, True), [ev(MFA, True)], SUPPORTED, None),
    ("claim true, evidence false", MFA, claim(MFA, True), [ev(MFA, False)], CONTRADICTED, None),
    ("EDR 94% vs 'all endpoints'", EDR, claim(EDR, True), [ev(EDR, 0.94)], CONTRADICTED, None),
    ("no evidence source exists", TRAINING, claim(TRAINING, True), [], UNVERIFIABLE, None),
    ("low confidence, evidence agrees", MFA, claim(MFA, True, 0.6), [ev(MFA, True)],
     NEEDS_REVIEW, None),
    ("low confidence, evidence contradicts", MFA, claim(MFA, True, 0.6), [ev(MFA, False)],
     NEEDS_REVIEW, None),
    ("evidence sources disagree", RESTORE, claim(RESTORE, True),
     [ev(RESTORE, True, "backup_log.txt", 0.9), ev(RESTORE, False, "msp_notes.txt", 0.9)],
     NEEDS_REVIEW, None),
    ("claim false, evidence true", MFA, claim(MFA, False), [ev(MFA, True)],
     SUPPORTED, "under-report"),
    # --- Precedence and boundaries -------------------------------------------
    ("low confidence beats no source", TRAINING, claim(TRAINING, True, 0.5), [],
     NEEDS_REVIEW, None),
    ("confidence exactly 0.8 is trusted", MFA, claim(MFA, True, 0.8), [ev(MFA, True)],
     SUPPORTED, None),
    ("low-confidence LLM evidence", RESTORE, claim(RESTORE, True),
     [ev(RESTORE, True, "msp_notes.txt", 0.7)], NEEDS_REVIEW, None),
    ("claim value null", MFA, claim(MFA, None), [ev(MFA, True)], NEEDS_REVIEW, None),
    ("claim missing entirely", MFA, None, [ev(MFA, True)], NEEDS_REVIEW, None),
    ("source exists but nothing found", RESTORE, claim(RESTORE, True), [], UNVERIFIABLE, None),
    ("evidence present but value unknown", MFA, claim(MFA, True), [ev(MFA, None)],
     UNVERIFIABLE, None),
    # --- Value kinds ---------------------------------------------------------
    ("EDR 100% vs 'all endpoints'", EDR, claim(EDR, True), [ev(EDR, 1.0)], SUPPORTED, None),
    ("claim false, evidence false", MFA, claim(MFA, False), [ev(MFA, False)],
     SUPPORTED, "not in place"),
    ("patches faster than claimed", PATCH, claim(PATCH, 14), [ev(PATCH, 9)], SUPPORTED, None),
    ("patches exactly as claimed", PATCH, claim(PATCH, 14), [ev(PATCH, 14)], SUPPORTED, None),
    ("patches slower than claimed", PATCH, claim(PATCH, 14), [ev(PATCH, 21)],
     CONTRADICTED, None),
]
# fmt: on


@pytest.mark.parametrize(
    "control_id, claimed, evidence, status, note",
    [case[1:] for case in CASES],
    ids=[case[0] for case in CASES],
)
def test_compare_control(control_id, claimed, evidence, status, note):
    finding = compare_control(control_id, claimed, evidence)
    assert finding.status == status
    assert finding.control_id == control_id
    assert finding.claim == claimed
    assert finding.evidence == evidence
    assert finding.reason.strip()
    if note is None:
        assert finding.note is None
    else:
        assert note in finding.note


def test_compare_all_returns_one_finding_per_control_in_order():
    findings = compare_all(
        claims=[claim(EDR, True), claim(MFA, True)],
        evidence=[ev(EDR, 0.94), ev(MFA, True), ev(PATCH, 9)],
    )
    assert [f.control_id for f in findings] == list(ControlId)
    by_id = {f.control_id: f for f in findings}
    assert by_id[EDR].status == CONTRADICTED
    assert by_id[EDR].evidence == [ev(EDR, 0.94)]
    assert by_id[MFA].status == SUPPORTED
    assert by_id[PATCH].status == NEEDS_REVIEW  # evidence but no claim
