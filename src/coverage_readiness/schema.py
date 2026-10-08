"""Canonical controls, claims, evidence and findings.

Every carrier's wording maps onto these ten controls. Claims come from the application,
evidence comes from the MSP, and a Finding is the deterministic verdict for one control.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ControlId(StrEnum):
    MFA_EMAIL = "mfa_email"
    MFA_REMOTE_ACCESS = "mfa_remote_access"
    MFA_PRIVILEGED = "mfa_privileged"
    EDR_ALL_ENDPOINTS = "edr_all_endpoints"
    BACKUPS_OFFLINE_IMMUTABLE = "backups_offline_immutable"
    BACKUP_RESTORE_TESTED = "backup_restore_tested"
    CRITICAL_PATCH_DAYS = "critical_patch_days"
    EMAIL_FILTERING = "email_filtering"
    SECURITY_AWARENESS_TRAINING = "security_awareness_training"
    INCIDENT_RESPONSE_PLAN = "incident_response_plan"


class ValueKind(StrEnum):
    """How a control's claim and evidence values are typed."""

    BOOL = "bool"  # claim: bool, evidence: bool
    COVERAGE = "coverage"  # claim: bool ("on all"), evidence: fraction covered, 0.0-1.0
    DAYS = "days"  # claim: int days, evidence: int days observed


class ControlSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    description: str
    kind: ValueKind
    evidence_sources: tuple[str, ...]  # empty means no source can verify this control


CONTROLS: dict[ControlId, ControlSpec] = {
    ControlId.MFA_EMAIL: ControlSpec(
        description="Multi-factor authentication is required for all users to access email.",
        kind=ValueKind.BOOL,
        evidence_sources=("m365_mfa",),
    ),
    ControlId.MFA_REMOTE_ACCESS: ControlSpec(
        description="Multi-factor authentication is required for remote access (VPN, RDP).",
        kind=ValueKind.BOOL,
        evidence_sources=("msp_notes",),
    ),
    ControlId.MFA_PRIVILEGED: ControlSpec(
        description="Multi-factor authentication is required for admin and privileged accounts.",
        kind=ValueKind.BOOL,
        evidence_sources=("m365_mfa",),
    ),
    ControlId.EDR_ALL_ENDPOINTS: ControlSpec(
        description="An EDR agent is installed and active on every endpoint.",
        kind=ValueKind.COVERAGE,
        evidence_sources=("edr_inventory",),
    ),
    ControlId.BACKUPS_OFFLINE_IMMUTABLE: ControlSpec(
        description="At least one backup copy is offline, air-gapped or immutable.",
        kind=ValueKind.BOOL,
        evidence_sources=("backup_log", "msp_notes"),
    ),
    ControlId.BACKUP_RESTORE_TESTED: ControlSpec(
        description="A restore from backup was tested successfully in the last 12 months.",
        kind=ValueKind.BOOL,
        evidence_sources=("backup_log", "msp_notes"),
    ),
    ControlId.CRITICAL_PATCH_DAYS: ControlSpec(
        description="Critical security patches are deployed within this many days of release.",
        kind=ValueKind.DAYS,
        evidence_sources=("patches",),
    ),
    ControlId.EMAIL_FILTERING: ControlSpec(
        description="Inbound email is filtered for malicious links and attachments.",
        kind=ValueKind.BOOL,
        evidence_sources=("msp_notes",),
    ),
    ControlId.SECURITY_AWARENESS_TRAINING: ControlSpec(
        description="Staff complete security awareness training at least annually.",
        kind=ValueKind.BOOL,
        evidence_sources=(),
    ),
    ControlId.INCIDENT_RESPONSE_PLAN: ControlSpec(
        description="A written incident response plan exists.",
        kind=ValueKind.BOOL,
        evidence_sources=(),
    ),
}


class ClaimedControl(BaseModel):
    """What the application says about one control."""

    control_id: ControlId
    value: bool | int | None = Field(description="null when the answer does not say")
    confidence: float = Field(ge=0.0, le=1.0)
    source_quote: str | None = Field(
        default=None, description="Verbatim text from the application answer"
    )
    source_question_id: str | None = None


class EvidencedControl(BaseModel):
    """What one piece of MSP evidence shows about one control."""

    control_id: ControlId
    value: bool | int | float | None
    source: str = Field(description="Evidence file or system, e.g. 'edr_inventory.json'")
    detail: str = Field(description="Human-readable summary, e.g. 'EDR active on 47 of 50'")
    # Set only for evidence read by the LLM from free text. Parsers leave both as None.
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source_quote: str | None = None


class FindingStatus(StrEnum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    UNVERIFIABLE = "unverifiable"
    NEEDS_REVIEW = "needs_review"


class Finding(BaseModel):
    """The verdict for one control: the claim, the evidence and why."""

    control_id: ControlId
    status: FindingStatus
    claim: ClaimedControl | None
    evidence: list[EvidencedControl] = Field(default_factory=list)
    reason: str
    note: str | None = None
