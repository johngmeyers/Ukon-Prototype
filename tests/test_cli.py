"""End-to-end: CLI -> pipeline -> real parsers + fake LLM -> comparison -> markdown report."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from coverage_readiness import cli
from coverage_readiness.llm.client import FakeLLMClient
from coverage_readiness.llm.mapper import APPLICATION_PROMPT
from coverage_readiness.schema import ControlId

BIRCH = Path(__file__).parent.parent / "fixtures" / "businesses" / "birch_logistics"


def birch_replies() -> list[str]:
    """Canned LLM replies in call order: application, msp_notes.txt, backup_log.txt."""
    values = {
        ControlId.CRITICAL_PATCH_DAYS: 30,
        ControlId.INCIDENT_RESPONSE_PLAN: False,
    }
    claims = [
        {
            "control_id": cid.value,
            "value": values.get(cid, True),
            "confidence": 0.95,
            "source_quote": "quote",
            "source_question_id": f"a{i}",
        }
        for i, cid in enumerate(ControlId, start=1)
    ]

    def item(cid, value):
        return {
            "control_id": cid,
            "value": value,
            "detail": f"{cid} detail",
            "source_quote": f"{cid} quote",
            "confidence": 0.9,
        }

    notes = [
        item("mfa_remote_access", True),
        item("email_filtering", True),
        item("backups_offline_immutable", True),
        item("backup_restore_tested", False),
    ]
    backup_log = [item("backups_offline_immutable", True), item("backup_restore_tested", False)]
    return [
        json.dumps({"claims": claims}),
        json.dumps({"items": notes}),
        json.dumps({"items": backup_log}),
    ]


@pytest.fixture
def fake(monkeypatch) -> FakeLLMClient:
    client = FakeLLMClient(birch_replies(), model="claude-opus-5-5")
    monkeypatch.setattr(cli, "make_client", lambda: client)
    return client


def run(*args: str):
    return CliRunner().invoke(cli.app, ["check", *args])


def test_check_birch_writes_contradictions_first(fake, tmp_path):
    out = tmp_path / "report.md"
    result = run(
        str(BIRCH),
        "--carrier", "carrier_a",
        "--as-of", "2026-09-30",
        "--runs-dir", str(tmp_path / "runs"),
        "--output", str(out),
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    report = out.read_text()

    assert "# Coverage readiness: birch_logistics · carrier_a" in report
    assert "As of 2026-09-30 · **2** contradicted · **0** needs review" in report
    assert "LLM: 3 calls (0 retries)" in report
    headings = [line for line in report.splitlines() if line.startswith("## ")]
    assert headings == ["## Contradicted (2)", "## Unverifiable (2)", "## Supported (6)"]

    contradicted = report.split("## Unverifiable")[0]
    assert "EDR on all endpoints" in contradicted
    assert "47 of 50 devices (94%)" in contradicted
    assert "coverage 94%, required 100%" in contradicted
    assert "Restore tested (12 mo)" in contradicted
    assert '"backup_restore_tested quote"' in contradicted  # quotes shown where action needed

    supported = report.split("## Supported")[1]
    assert '"email_filtering quote"' not in supported  # but not in the supported section

    [log] = (tmp_path / "runs").glob("*.jsonl")
    records = [json.loads(line) for line in log.read_text().splitlines()]
    assert [r["prompt_version"] for r in records] == [
        APPLICATION_PROMPT,
        "map_evidence_notes_v1",
        "map_evidence_notes_v1",
    ]


def test_missing_carrier_exits_cleanly(fake, tmp_path):
    result = run(str(BIRCH), "--carrier", "carrier_z", "--runs-dir", str(tmp_path))
    assert result.exit_code == 2
    assert "carrier_z.yaml" in result.output
