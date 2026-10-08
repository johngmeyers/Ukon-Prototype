"""Turn free text into canonical controls: answers into claims, MSP notes into evidence."""

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationInfo, model_validator

from coverage_readiness.llm.client import LLMClient, Prompt, RunLog, call_structured
from coverage_readiness.schema import (
    CONTROLS,
    ClaimedControl,
    ControlId,
    EvidencedControl,
    ValueKind,
)

PROMPTS = Path(__file__).parent / "prompts"
APPLICATION_PROMPT = "map_application_v2"
NOTES_PROMPT = "map_evidence_notes_v1"


def load_prompt(version: str, **values: str) -> Prompt:
    template = (PROMPTS / f"{version}.md").read_text(encoding="utf-8")
    return Prompt(version=version, system=template.format(**values))


def describe_controls(control_ids: list[ControlId]) -> str:
    return "\n".join(
        f"- `{cid}` ({CONTROLS[cid].kind}): {CONTROLS[cid].description}" for cid in control_ids
    )


# --- Application answers -> claims ------------------------------------------


class ApplicationMapping(BaseModel):
    claims: list[ClaimedControl]

    @model_validator(mode="after")
    def one_claim_per_control(self, info: ValidationInfo) -> "ApplicationMapping":
        ids = [c.control_id.value for c in self.claims]
        missing = {c.value for c in ControlId} - set(ids)
        duplicates = {cid for cid in ids if ids.count(cid) > 1}
        if missing or duplicates:
            raise ValueError(
                f"need exactly one claim per control; missing={sorted(missing)}, "
                f"duplicated={sorted(duplicates)}"
            )
        question_ids = (info.context or {}).get("question_ids")
        for claim in self.claims:
            if question_ids and claim.source_question_id not in (None, *question_ids):
                raise ValueError(f"{claim.control_id}: unknown question {claim.source_question_id}")
            wants_days = CONTROLS[claim.control_id].kind == ValueKind.DAYS
            if claim.value is not None and isinstance(claim.value, bool) == wants_days:
                expected = "an integer number of days" if wants_days else "true or false"
                raise ValueError(f"{claim.control_id}: expected {expected}, got {claim.value!r}")
        return self


def render_application(carrier: dict[str, Any], application: dict[str, Any]) -> str:
    answers = {a["question_id"]: a["answer"] for a in application["answers"]}
    lines = [f'<application carrier="{carrier["carrier"]}">']
    for q in carrier["questions"]:
        lines.append(f'<question id="{q["id"]}">{q["text"]}</question>')
        lines.append(f'<answer question_id="{q["id"]}">{answers.get(q["id"], "")}</answer>')
    lines.append("</application>")
    return "\n".join(lines)


def map_application(
    client: LLMClient,
    carrier: dict[str, Any],
    application: dict[str, Any],
    log: RunLog,
    prompt_version: str = APPLICATION_PROMPT,
) -> list[ClaimedControl]:
    prompt = load_prompt(prompt_version, controls=describe_controls(list(ControlId)))
    mapping = call_structured(
        client,
        prompt=prompt,
        user=render_application(carrier, application),
        output_model=ApplicationMapping,
        log=log,
        context={"question_ids": [q["id"] for q in carrier["questions"]]},
    )
    order = list(ControlId)
    return sorted(mapping.claims, key=lambda c: order.index(c.control_id))


# --- Free-text MSP evidence -> evidence -------------------------------------


class NotesItem(BaseModel):
    control_id: ControlId
    value: bool | None
    detail: str
    source_quote: str
    confidence: float = Field(ge=0.0, le=1.0)


class NotesReading(BaseModel):
    items: list[NotesItem]

    @model_validator(mode="after")
    def only_allowed_controls(self, info: ValidationInfo) -> "NotesReading":
        allowed = (info.context or {}).get("allowed", set(ControlId))
        ids = [i.control_id.value for i in self.items]
        if extra := sorted(set(ids) - {c.value for c in allowed}):
            raise ValueError(f"reported controls that were not asked for: {extra}")
        if len(ids) != len(set(ids)):
            raise ValueError("reported the same control more than once")
        return self


def notes_controls(source: str) -> list[ControlId]:
    """Controls that a free-text evidence source (e.g. 'msp_notes') can speak to."""
    return [cid for cid, spec in CONTROLS.items() if source in spec.evidence_sources]


def read_evidence_notes(
    client: LLMClient, path: Path, source: str, as_of: date, log: RunLog
) -> list[EvidencedControl]:
    allowed = notes_controls(source)
    prompt = load_prompt(
        NOTES_PROMPT,
        controls=describe_controls(allowed),
        as_of=as_of.isoformat(),
        window_start=(as_of - timedelta(days=365)).isoformat(),
    )
    text = path.read_text(encoding="utf-8")
    reading = call_structured(
        client,
        prompt=prompt,
        user=f'<evidence file="{path.name}">\n{text}\n</evidence>',
        output_model=NotesReading,
        log=log,
        context={"allowed": allowed},
    )
    return [
        EvidencedControl(
            control_id=item.control_id,
            value=item.value,
            source=path.name,
            detail=item.detail,
            confidence=item.confidence,
            source_quote=item.source_quote,
        )
        for item in reading.items
    ]
