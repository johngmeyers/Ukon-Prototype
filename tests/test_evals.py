"""Eval dataset integrity and harness scoring. No API calls."""

from datetime import date

import pytest
import yaml

from coverage_readiness.pipeline import Assessment
from coverage_readiness.schema import (
    ClaimedControl,
    ControlId,
    Finding,
    FindingStatus,
)
from evals.run_evals import (
    FIXTURES,
    UNSCORED,
    load_scenarios,
    materialize,
    metrics,
    same_value,
    score_scenario,
    stability,
)

SCENARIOS = load_scenarios()
CONTROL_IDS = {c.value for c in ControlId}
STATUSES = {s.value for s in FindingStatus}


def test_sixteen_scenarios_with_the_planned_mix():
    categories = [s.category for s in SCENARIOS]
    assert len(SCENARIOS) == 16
    assert {c: categories.count(c) for c in set(categories)} == {
        "clean": 4,
        "contradiction": 5,
        "ambiguous": 3,
        "combined_split": 2,
        "under_report": 1,
        "injection": 1,
    }


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_scenario_labels_are_complete_and_valid(scenario):
    assert set(scenario.expected_claims) == CONTROL_IDS
    assert set(scenario.expected_status) == CONTROL_IDS
    assert set(scenario.expected_status.values()) <= STATUSES
    carrier = yaml.safe_load((FIXTURES / "carriers" / f"{scenario.carrier}.yaml").read_text())
    question_ids = {q["id"] for q in carrier["questions"]}
    assert set(scenario.answers) <= question_ids
    for path in scenario.dir.iterdir():
        if path.name != "scenario.yaml":  # evidence overrides must replace a real base file
            assert (FIXTURES / "businesses" / scenario.base / path.name).exists(), path.name


def test_materialize_applies_answer_and_evidence_overrides(tmp_path):
    scenario = next(s for s in SCENARIOS if s.id == "05_contra_mfa_email_a")
    business = materialize(scenario, tmp_path)
    assert (business / "m365_mfa.csv").read_text().count("Disabled") == 2

    scenario = next(s for s in SCENARIOS if s.id == "10_ambiguous_mfa_most_a")
    business = materialize(scenario, tmp_path)
    app = yaml.safe_load((business / "application_carrier_a.yaml").read_text())
    answers = {a["question_id"]: a["answer"] for a in app["answers"]}
    assert answers["a1"] == "MFA is on for most of our systems."
    assert answers["a2"].startswith("Yes. The VPN requires MFA")  # untouched
    assert all(isinstance(a, str) for a in answers.values())


def test_same_value_does_not_confuse_bool_and_int():
    assert same_value(True, True)
    assert same_value(None, None)
    assert not same_value(True, 1)
    assert not same_value(14, 14.0)


def fake_assessment(statuses: dict[str, str], claims: dict[str, object]) -> Assessment:
    return Assessment(
        business="x",
        carrier="carrier_a",
        as_of=date(2026, 9, 30),
        claims=[
            ClaimedControl(control_id=cid, value=claims[cid], confidence=0.9) for cid in claims
        ],
        evidence=[],
        findings=[
            Finding(control_id=cid, status=status, claim=None, reason="r")
            for cid, status in statuses.items()
        ],
        llm_calls=[
            {
                "attempt": 1,
                "input_tokens": 100,
                "output_tokens": 10,
                "cost_usd": 0.01,
                "latency_ms": 1000,
            },
        ],  # fmt: skip
    )


def test_scoring_counts_contradictions_and_unscored_claims():
    scenario = next(s for s in SCENARIOS if s.id == "10_ambiguous_mfa_most_a")
    assert scenario.expected_claims["mfa_email"] == UNSCORED
    statuses = dict(scenario.expected_status)
    claims = dict(scenario.expected_claims, mfa_email=True)
    statuses["mfa_remote_access"] = "contradicted"  # one false alarm
    scored = score_scenario(scenario, fake_assessment(statuses, claims), None)

    m = metrics([scored])
    assert m["mapping_accuracy"] == 1.0  # 9 scored fields, unscored one skipped
    assert m["mapping_accuracy_per_field"]["mfa_email"] is None
    assert m["status_accuracy"] == 0.9
    assert m["contradiction_recall"] is None  # nothing expected contradicted
    assert m["contradiction_precision"] == 0.0
    assert m["review_rate"] == 0.1
    assert m["cost_usd"] == 0.01


def test_crashed_scenario_scores_as_wrong_not_skipped():
    scenario = next(s for s in SCENARIOS if s.id == "16_injection_a")
    scored = score_scenario(scenario, None, "LLMOutputError: boom")
    m = metrics([scored])
    assert m["errors"] == 1
    assert m["status_accuracy"] == 0.0
    assert m["contradiction_recall"] == 0.0


def test_stability_compares_runs():
    scenario = SCENARIOS[0]
    a = score_scenario(
        scenario, fake_assessment(scenario.expected_status, scenario.expected_claims), None
    )
    flipped = dict(scenario.expected_status, mfa_email="needs_review")
    b = score_scenario(scenario, fake_assessment(flipped, scenario.expected_claims), None)
    assert stability([[a]]) is None
    assert stability([[a], [a]]) == 1.0
    assert stability([[a], [b]]) == 0.9
