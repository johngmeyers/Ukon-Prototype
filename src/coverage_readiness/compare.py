"""Deterministic claim-vs-evidence comparison. No LLM calls; every rule is in tests/test_compare.py.

Precedence, highest first:
  1. needs_review  claim missing, claim value null, or claim confidence below threshold
  2. needs_review  any LLM-read evidence below the confidence threshold
  3. unverifiable  control has no evidence source, or no usable evidence was found
  4. needs_review  evidence sources disagree with each other
  5. supported / contradicted  compare the claim to the evidence
"""

from coverage_readiness import config
from coverage_readiness.schema import (
    CONTROLS,
    ClaimedControl,
    ControlId,
    EvidencedControl,
    Finding,
    FindingStatus,
    ValueKind,
)


def compare_control(
    control_id: ControlId,
    claim: ClaimedControl | None,
    evidence: list[EvidencedControl],
    thresholds: dict[str, float] = config.THRESHOLDS,
) -> Finding:
    spec = CONTROLS[control_id]
    min_confidence = thresholds["min_confidence"]

    def finding(status: FindingStatus, reason: str, note: str | None = None) -> Finding:
        return Finding(
            control_id=control_id,
            status=status,
            claim=claim,
            evidence=evidence,
            reason=reason,
            note=note,
        )

    # 1. Is the claim itself trustworthy?
    if claim is None:
        return finding(FindingStatus.NEEDS_REVIEW, "No application answer was mapped here.")
    if claim.value is None:
        return finding(
            FindingStatus.NEEDS_REVIEW, "The application doesn't say clearly what is in place."
        )
    if claim.confidence < min_confidence:
        return finding(
            FindingStatus.NEEDS_REVIEW,
            f"Mapping confidence {claim.confidence:.2f} is below {min_confidence}; "
            "confirm what the answer actually claims.",
        )
    if not _claim_has_expected_type(spec.kind, claim.value):
        return finding(
            FindingStatus.NEEDS_REVIEW, f"Claim value {claim.value!r} has the wrong type."
        )

    # 2. Is any LLM-read evidence shaky?
    shaky = [e for e in evidence if e.confidence is not None and e.confidence < min_confidence]
    if shaky:
        sources = ", ".join(e.source for e in shaky)
        return finding(
            FindingStatus.NEEDS_REVIEW,
            f"Evidence from {sources} was read with low confidence; confirm it.",
        )

    # 3. Is there anything to check against?
    if not spec.evidence_sources:
        return finding(
            FindingStatus.UNVERIFIABLE,
            "No evidence source can verify this control; it rests on the applicant's word.",
        )
    usable = [e for e in evidence if e.value is not None]
    if not usable:
        return finding(
            FindingStatus.UNVERIFIABLE,
            f"No usable evidence found (looked in: {', '.join(spec.evidence_sources)}).",
        )

    # 4. Do the evidence sources agree? Days: each source meets the claim or not.
    #    Everything else: each source shows the control in place or not.
    if spec.kind == ValueKind.DAYS:
        readings = {e.source: e.value <= claim.value for e in usable}
        labels = ("meets the claim", "misses the claim")
    else:
        readings = {e.source: _in_place(spec.kind, e.value, thresholds) for e in usable}
        labels = ("shows it in place", "shows it not in place")
    if len(set(readings.values())) > 1:
        detail = "; ".join(
            f"{src} {labels[0] if ok else labels[1]}" for src, ok in readings.items()
        )
        return finding(FindingStatus.NEEDS_REVIEW, f"Evidence sources disagree: {detail}.")
    agreed = next(iter(readings.values()))

    # 5. Compare.
    if spec.kind == ValueKind.DAYS:
        slowest = max(e.value for e in usable)
        if agreed:
            return finding(
                FindingStatus.SUPPORTED,
                f"Slowest critical patch took {slowest} days, within the claimed {claim.value}.",
            )
        return finding(
            FindingStatus.CONTRADICTED,
            f"Slowest critical patch took {slowest} days; the application claims {claim.value}.",
        )

    in_place = agreed
    if claim.value and in_place:
        return finding(FindingStatus.SUPPORTED, "Evidence confirms the control is in place.")
    if claim.value:
        return finding(
            FindingStatus.CONTRADICTED,
            "The application says this is in place; the evidence shows it isn't"
            + _coverage_suffix(spec.kind, usable),
        )
    if in_place:
        return finding(
            FindingStatus.SUPPORTED,
            "The application says this is not in place, but the evidence shows it is.",
            note="The client may under-report this control; consider correcting the answer.",
        )
    return finding(
        FindingStatus.SUPPORTED,
        "The application says this is not in place, and the evidence agrees.",
        note="Control is not in place. The answer is accurate, but it's a gap to close.",
    )


def compare_all(
    claims: list[ClaimedControl],
    evidence: list[EvidencedControl],
    thresholds: dict[str, float] = config.THRESHOLDS,
) -> list[Finding]:
    """One finding per canonical control, in ControlId order."""
    by_id = {c.control_id: c for c in claims}
    return [
        compare_control(
            cid, by_id.get(cid), [e for e in evidence if e.control_id == cid], thresholds
        )
        for cid in ControlId
    ]


def _claim_has_expected_type(kind: ValueKind, value: bool | int) -> bool:
    if kind == ValueKind.DAYS:
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, bool)


def _in_place(kind: ValueKind, value: bool | int | float, thresholds: dict[str, float]) -> bool:
    """Whether one piece of evidence shows the control is in place."""
    if kind == ValueKind.COVERAGE:
        return float(value) >= thresholds["full_coverage"]
    return bool(value)


def _coverage_suffix(kind: ValueKind, usable: list[EvidencedControl]) -> str:
    if kind != ValueKind.COVERAGE:
        return "."
    return f" (coverage {min(float(e.value) for e in usable):.0%}, required 100%)."
