from datetime import date

from coverage_readiness.pipeline import Assessment
from coverage_readiness.report import render_markdown
from coverage_readiness.schema import (
    ClaimedControl,
    ControlId,
    EvidencedControl,
    Finding,
    FindingStatus,
)


def make_finding(control_id, status, value=True, quote="Yes", evidence=(), note=None):
    claim = ClaimedControl(
        control_id=control_id,
        value=value,
        confidence=0.9,
        source_quote=quote,
        source_question_id="a1",
    )
    return Finding(
        control_id=control_id,
        status=status,
        claim=claim,
        evidence=list(evidence),
        reason="reason",
        note=note,
    )


def render(*findings, calls=()):
    return render_markdown(
        Assessment(
            business="acme",
            carrier="carrier_a",
            as_of=date(2026, 9, 30),
            claims=[],
            evidence=[],
            findings=list(findings),
            llm_calls=list(calls),
        )
    )


def test_sections_follow_fixed_order_and_skip_empty_ones():
    report = render(
        make_finding(ControlId.MFA_EMAIL, FindingStatus.SUPPORTED),
        make_finding(ControlId.INCIDENT_RESPONSE_PLAN, FindingStatus.UNVERIFIABLE),
        make_finding(ControlId.EDR_ALL_ENDPOINTS, FindingStatus.CONTRADICTED),
    )
    headings = [line for line in report.splitlines() if line.startswith("## ")]
    assert headings == ["## Contradicted (1)", "## Unverifiable (1)", "## Supported (1)"]
    assert "**1** contradicted · **0** needs review · **1** unverifiable" in report


def test_claim_cell_formats_values():
    report = render(
        make_finding(ControlId.CRITICAL_PATCH_DAYS, FindingStatus.SUPPORTED, value=14, quote="14"),
        make_finding(ControlId.MFA_EMAIL, FindingStatus.NEEDS_REVIEW, value=None, quote=None),
        make_finding(ControlId.MFA_PRIVILEGED, FindingStatus.SUPPORTED, value=False, quote="No"),
    )
    assert '**14 days** "14" (a1, conf 0.90)' in report
    assert "**unclear** (a1, conf 0.90)" in report
    assert '**no** "No"' in report


def test_pipes_in_text_do_not_break_the_table():
    report = render(make_finding(ControlId.MFA_EMAIL, FindingStatus.CONTRADICTED, quote="a | b"))
    assert '"a \\| b"' in report


def test_evidence_quote_and_note_render():
    evidence = EvidencedControl(
        control_id=ControlId.MFA_REMOTE_ACCESS,
        value=False,
        source="msp_notes.txt",
        detail="VPN has no MFA",
        confidence=0.95,
        source_quote="No MFA on the VPN yet.",
    )
    report = render(
        make_finding(
            ControlId.MFA_REMOTE_ACCESS,
            FindingStatus.CONTRADICTED,
            evidence=[evidence],
            note="Fix it.",
        )
    )
    assert 'VPN has no MFA (msp_notes.txt, conf 0.95) "No MFA on the VPN yet."' in report
    assert "reason **Note:** Fix it." in report


def test_llm_summary_totals_calls():
    calls = [
        {"input_tokens": 1000, "output_tokens": 200, "cost_usd": 0.008, "latency_ms": 1500,
         "model": "claude-opus-5-5", "attempt": 1},
        {"input_tokens": 500, "output_tokens": 100, "cost_usd": 0.004, "latency_ms": 500,
         "model": "claude-opus-5-5", "attempt": 2},
    ]  # fmt: skip
    report = render(calls=calls)
    assert "LLM: 2 calls (1 retries) · 1,800 tokens · $0.012 · 2.0s · claude-opus-5-5" in report
