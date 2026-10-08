"""Markdown readiness report: contradictions first, then needs review, unverifiable, supported."""

from coverage_readiness.pipeline import Assessment
from coverage_readiness.schema import (
    CONTROLS,
    ClaimedControl,
    ControlId,
    EvidencedControl,
    Finding,
    FindingStatus,
    ValueKind,
)

SECTIONS = [
    (FindingStatus.CONTRADICTED, "Contradicted", "Fix the environment or correct the answer."),
    (FindingStatus.NEEDS_REVIEW, "Needs review", "A person must decide. Never auto-resolved."),
    (FindingStatus.UNVERIFIABLE, "Unverifiable", "Nothing available can confirm the claim."),
    (FindingStatus.SUPPORTED, "Supported", "The evidence backs the answer."),
]

# Sections where someone must act; these rows also show the evidence quotes.
ACTIONABLE = {FindingStatus.CONTRADICTED, FindingStatus.NEEDS_REVIEW}

LABELS = {
    ControlId.MFA_EMAIL: "MFA on email",
    ControlId.MFA_REMOTE_ACCESS: "MFA on remote access",
    ControlId.MFA_PRIVILEGED: "MFA on admin accounts",
    ControlId.EDR_ALL_ENDPOINTS: "EDR on all endpoints",
    ControlId.BACKUPS_OFFLINE_IMMUTABLE: "Offline/immutable backups",
    ControlId.BACKUP_RESTORE_TESTED: "Restore tested (12 mo)",
    ControlId.CRITICAL_PATCH_DAYS: "Critical patch days",
    ControlId.EMAIL_FILTERING: "Email filtering",
    ControlId.SECURITY_AWARENESS_TRAINING: "Awareness training",
    ControlId.INCIDENT_RESPONSE_PLAN: "Incident response plan",
}


def render_markdown(assessment: Assessment) -> str:
    counts = {s: sum(f.status == s for f in assessment.findings) for s, _, _ in SECTIONS}
    lines = [
        f"# Coverage readiness: {assessment.business} · {assessment.carrier}",
        "",
        f"As of {assessment.as_of} · "
        + " · ".join(f"**{counts[s]}** {title.lower()}" for s, title, _ in SECTIONS),
        "",
        _llm_summary(assessment.llm_calls),
    ]
    for status, title, blurb in SECTIONS:
        findings = [f for f in assessment.findings if f.status == status]
        if not findings:
            continue
        lines += [
            "",
            f"## {title} ({len(findings)})",
            "",
            blurb,
            "",
            "| Control | Claim | Evidence | Why |",
            "|---|---|---|---|",
        ]
        lines += [_row(f, quotes=status in ACTIONABLE) for f in findings]
    return "\n".join(lines) + "\n"


def _row(finding: Finding, quotes: bool) -> str:
    why = finding.reason + (f" **Note:** {finding.note}" if finding.note else "")
    cells = [
        f"**{LABELS[finding.control_id]}**",
        _claim_cell(finding.claim),
        _evidence_cell(finding.evidence, quotes),
        why,
    ]
    return "| " + " | ".join(_escape(c) for c in cells) + " |"


def _claim_cell(claim: ClaimedControl | None) -> str:
    if claim is None:
        return "no answer"
    if claim.value is None:
        value = "unclear"
    elif CONTROLS[claim.control_id].kind == ValueKind.DAYS:
        value = f"{claim.value} days"
    else:
        value = "yes" if claim.value else "no"
    quote = f' "{claim.source_quote}"' if claim.source_quote else ""
    where = f"{claim.source_question_id}, " if claim.source_question_id else ""
    return f"**{value}**{quote} ({where}conf {claim.confidence:.2f})"


def _evidence_cell(evidence: list[EvidencedControl], quotes: bool) -> str:
    if not evidence:
        return "none"
    parts = []
    for e in evidence:
        part = f"{e.detail} ({e.source}"
        part += f", conf {e.confidence:.2f})" if e.confidence is not None else ")"
        if quotes and e.source_quote:
            part += f' "{e.source_quote}"'
        parts.append(part)
    return " / ".join(parts)


def _llm_summary(calls: list[dict]) -> str:
    if not calls:
        return "LLM: no calls"
    tokens = sum(c["input_tokens"] + c["output_tokens"] for c in calls)
    costs = [c["cost_usd"] for c in calls]
    cost = "unknown" if None in costs else f"${sum(costs):.3f}"
    seconds = sum(c["latency_ms"] for c in calls) / 1000
    models = ", ".join(sorted({c["model"] for c in calls}))
    retries = sum(c["attempt"] > 1 for c in calls)
    return (
        f"LLM: {len(calls)} calls ({retries} retries) · {tokens:,} tokens · {cost} · "
        f"{seconds:.1f}s · {models}"
    )


def _escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")
