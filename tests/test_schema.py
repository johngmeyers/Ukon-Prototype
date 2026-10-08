import pytest
from pydantic import ValidationError

from coverage_readiness.schema import (
    CONTROLS,
    ClaimedControl,
    ControlId,
    EvidencedControl,
    Finding,
    FindingStatus,
)


def test_every_control_has_a_spec_with_description():
    assert set(CONTROLS) == set(ControlId)
    for control_id, spec in CONTROLS.items():
        assert spec.description.strip(), control_id


def test_exactly_two_controls_have_no_evidence_source():
    unverifiable = {cid for cid, spec in CONTROLS.items() if not spec.evidence_sources}
    assert unverifiable == {
        ControlId.SECURITY_AWARENESS_TRAINING,
        ControlId.INCIDENT_RESPONSE_PLAN,
    }


@pytest.mark.parametrize("confidence", [-0.1, 1.01, 2])
def test_invalid_confidence_is_rejected(confidence):
    with pytest.raises(ValidationError):
        ClaimedControl(control_id=ControlId.MFA_EMAIL, value=True, confidence=confidence)


@pytest.mark.parametrize("confidence", [0.0, 0.8, 1.0])
def test_boundary_confidence_is_accepted(confidence):
    claim = ClaimedControl(control_id=ControlId.MFA_EMAIL, value=True, confidence=confidence)
    assert claim.confidence == confidence


def test_unknown_control_id_is_rejected():
    with pytest.raises(ValidationError):
        ClaimedControl(control_id="mfa_everywhere", value=True, confidence=0.9)


def test_claim_value_keeps_bool_and_int_distinct():
    assert ClaimedControl(control_id="mfa_email", value=True, confidence=1).value is True
    days = ClaimedControl(control_id="critical_patch_days", value=14, confidence=1)
    assert days.value == 14 and type(days.value) is int


def test_finding_round_trips_through_json():
    finding = Finding(
        control_id=ControlId.EDR_ALL_ENDPOINTS,
        status=FindingStatus.CONTRADICTED,
        claim=ClaimedControl(
            control_id=ControlId.EDR_ALL_ENDPOINTS,
            value=True,
            confidence=0.95,
            source_quote="CrowdStrike is on every machine.",
            source_question_id="a4",
        ),
        evidence=[
            EvidencedControl(
                control_id=ControlId.EDR_ALL_ENDPOINTS,
                value=0.94,
                source="edr_inventory.json",
                detail="EDR active on 47 of 50 devices (94%)",
            )
        ],
        reason="Claim says all endpoints; evidence shows 94%.",
    )
    assert Finding.model_validate_json(finding.model_dump_json()) == finding
