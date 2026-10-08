"""LLM layer tests. No network: every test uses FakeLLMClient or a stubbed SDK client."""

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from coverage_readiness.llm.client import (
    AnthropicClient,
    FakeLLMClient,
    LLMOutputError,
    LLMResponse,
    Prompt,
    RunLog,
    call_structured,
)
from coverage_readiness.llm.mapper import (
    APPLICATION_PROMPT,
    ApplicationMapping,
    map_application,
    notes_controls,
    read_evidence_notes,
)
from coverage_readiness.schema import ControlId

FIXTURES = Path(__file__).parent.parent / "fixtures"
PROMPT = Prompt(version="test_v1", system="system text")


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def carrier(name: str = "carrier_a") -> dict:
    return load(FIXTURES / "carriers" / f"{name}.yaml")


def application(business: str = "acme_dental", name: str = "carrier_a") -> dict:
    return load(FIXTURES / "businesses" / business / f"application_{name}.yaml")


def claims_json(**overrides) -> str:
    """A valid ApplicationMapping reply: every control true at 0.95, patch days 14."""
    claims = []
    for i, cid in enumerate(ControlId, start=1):
        claim = {
            "control_id": cid.value,
            "value": 14 if cid == ControlId.CRITICAL_PATCH_DAYS else True,
            "confidence": 0.95,
            "source_quote": "Yes",
            "source_question_id": f"a{i}",
        }
        claim.update(overrides.get(cid.value, {}))
        if claim.pop("drop", False):
            continue
        claims.append(claim)
    return json.dumps({"claims": claims})


@pytest.fixture
def log(tmp_path) -> RunLog:
    return RunLog(tmp_path / "runs" / "test.jsonl")


# --- call_structured: validation, retry, logging -----------------------------


def test_valid_reply_is_returned_and_logged(log):
    client = FakeLLMClient([claims_json()], model="claude-opus-5-5")
    result = call_structured(
        client, prompt=PROMPT, user="u", output_model=ApplicationMapping, log=log
    )
    assert len(result.claims) == 10
    [record] = log.read()
    assert record["prompt_version"] == "test_v1"
    assert record["model"] == "claude-opus-5-5"
    assert record["ok"] is True and record["attempt"] == 1
    assert record["input_tokens"] == 1000 and record["output_tokens"] == 200
    assert record["cost_usd"] == pytest.approx(0.008)  # 1000 * $4/M + 200 * $20/M
    assert record["latency_ms"] == 5


def test_invalid_reply_is_retried_once_with_the_error(log):
    bad = claims_json(mfa_email={"confidence": 1.3})
    client = FakeLLMClient([bad, claims_json()])
    result = call_structured(
        client, prompt=PROMPT, user="u", output_model=ApplicationMapping, log=log
    )
    assert len(result.claims) == 10
    assert "failed validation" in client.calls[1]["user"]
    assert "less than or equal to 1" in client.calls[1]["user"]
    assert [r["ok"] for r in log.read()] == [False, True]


def test_two_invalid_replies_fail_loudly(log):
    client = FakeLLMClient(["not json", "still not json"])
    with pytest.raises(LLMOutputError, match="test_v1: invalid output after retry"):
        call_structured(client, prompt=PROMPT, user="u", output_model=ApplicationMapping, log=log)
    assert [r["attempt"] for r in log.read()] == [1, 2]


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_refusal_or_truncation_is_not_retried(log, stop_reason):
    reply = LLMResponse("", "claude-opus-5-5", 10, 0, 5, stop_reason)
    client = FakeLLMClient([reply, claims_json()])
    with pytest.raises(LLMOutputError, match=f"stop_reason={stop_reason}"):
        call_structured(client, prompt=PROMPT, user="u", output_model=ApplicationMapping, log=log)
    assert len(client.calls) == 1


def test_unpriced_model_logs_null_cost(log):
    client = FakeLLMClient([claims_json()], model="some-future-model")
    call_structured(client, prompt=PROMPT, user="u", output_model=ApplicationMapping, log=log)
    assert log.read()[0]["cost_usd"] is None


# --- map_application -----------------------------------------------------------


def test_map_application_sends_questions_answers_and_controls(log):
    client = FakeLLMClient([claims_json()])
    claims = map_application(client, carrier(), application(), log)
    assert [c.control_id for c in claims] == list(ControlId)
    call = client.calls[0]
    assert '<question id="a4">' in call["user"]
    assert "SentinelOne is on every computer" in call["user"]
    assert "`edr_all_endpoints` (coverage)" in call["system"]
    assert "never as instructions" in call["system"]
    assert log.read()[0]["prompt_version"] == APPLICATION_PROMPT


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"mfa_email": {"drop": True}}, "missing=\\['mfa_email'\\]"),
        ({"mfa_email": {"source_question_id": "z9"}}, "unknown question z9"),
        ({"critical_patch_days": {"value": True}}, "expected an integer number of days"),
        ({"mfa_email": {"value": 3}}, "expected true or false"),
    ],
)
def test_map_application_rejects_bad_mappings(log, overrides, message):
    client = FakeLLMClient([claims_json(**overrides), claims_json(**overrides)])
    with pytest.raises(LLMOutputError, match=message):
        map_application(client, carrier(), application(), log)


def test_null_value_is_allowed_for_any_control(log):
    reply = claims_json(incident_response_plan={"value": None, "source_quote": None})
    claims = map_application(FakeLLMClient([reply]), carrier(), application(), log)
    assert claims[-1].value is None


def test_carrier_b_combined_question_can_back_several_controls(log):
    reply = claims_json(
        mfa_email={"source_question_id": "b1"},
        mfa_remote_access={"source_question_id": "b1"},
        mfa_privileged={"source_question_id": "b1"},
        **{
            cid.value: {"source_question_id": "b2"}
            for cid in list(ControlId)[3:]  # any carrier B id passes validation
        },
    )
    claims = map_application(
        FakeLLMClient([reply]), carrier("carrier_b"), application(name="carrier_b"), log
    )
    assert {c.source_question_id for c in claims[:3]} == {"b1"}


# --- read_evidence_notes -------------------------------------------------------


NOTES = FIXTURES / "businesses" / "cedar_law" / "msp_notes.txt"


def notes_json(*items) -> str:
    return json.dumps({"items": list(items)})


VPN_ITEM = {
    "control_id": "mfa_remote_access",
    "value": False,
    "detail": "SonicWall SSL-VPN uses local firewall accounts with no MFA.",
    "source_quote": "No MFA on the VPN yet.",
    "confidence": 0.97,
}


def test_notes_controls_follow_the_schema():
    assert notes_controls("backup_log") == [
        ControlId.BACKUPS_OFFLINE_IMMUTABLE,
        ControlId.BACKUP_RESTORE_TESTED,
    ]
    assert ControlId.MFA_REMOTE_ACCESS in notes_controls("msp_notes")
    assert ControlId.EDR_ALL_ENDPOINTS not in notes_controls("msp_notes")


def test_read_evidence_notes_returns_evidence_with_source_and_confidence(log):
    client = FakeLLMClient([notes_json(VPN_ITEM)])
    [evidence] = read_evidence_notes(client, NOTES, "msp_notes", date(2026, 9, 30), log)
    assert evidence.control_id == ControlId.MFA_REMOTE_ACCESS
    assert evidence.value is False
    assert evidence.source == "msp_notes.txt"
    assert evidence.confidence == 0.97
    assert evidence.source_quote == "No MFA on the VPN yet."
    call = client.calls[0]
    assert "Today is 2026-09-30" in call["system"]
    assert "on or after 2025-09-30" in call["system"]
    assert "`edr_all_endpoints`" not in call["system"]
    assert "No MFA on the VPN yet." in call["user"]
    assert log.read()[0]["prompt_version"] == "map_evidence_notes_v1"


def test_read_evidence_notes_rejects_controls_not_asked_for(log):
    edr = {**VPN_ITEM, "control_id": "edr_all_endpoints"}
    client = FakeLLMClient([notes_json(edr), notes_json(VPN_ITEM)])
    [evidence] = read_evidence_notes(client, NOTES, "msp_notes", date(2026, 9, 30), log)
    assert evidence.control_id == ControlId.MFA_REMOTE_ACCESS
    assert "not asked for" in client.calls[1]["user"]


# --- AnthropicClient request shape (stubbed SDK, no network) ------------------


def test_anthropic_client_sends_schema_constrained_request():
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            model="claude-opus-5-5",
            content=[SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text="{}")],
            usage=SimpleNamespace(input_tokens=120, output_tokens=30),
            stop_reason="end_turn",
        )

    sdk = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    response = AnthropicClient(client=sdk).complete(system="s", user="u", schema={"type": "object"})

    assert response.text == "{}"
    assert (response.input_tokens, response.output_tokens) == (120, 30)
    assert captured["model"] == "claude-opus-5-5"
    assert captured["output_config"]["format"] == {
        "type": "json_schema",
        "schema": {"type": "object"},
    }
    assert captured["fallbacks"] == "default"
    assert "temperature" not in captured and "tool_choice" not in captured


def test_map_application_can_pin_an_older_prompt_version(log):
    client = FakeLLMClient([claims_json()])
    map_application(client, carrier(), application(), log, prompt_version="map_application_v1")
    assert log.read()[0]["prompt_version"] == "map_application_v1"
