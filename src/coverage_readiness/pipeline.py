"""Assess one business against one carrier application. Shared by the CLI and the evals."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from coverage_readiness.compare import compare_all
from coverage_readiness.llm.client import LLMClient, RunLog
from coverage_readiness.llm.mapper import APPLICATION_PROMPT, map_application, read_evidence_notes
from coverage_readiness.parsers.edr import parse_edr_inventory
from coverage_readiness.parsers.m365 import parse_m365_mfa
from coverage_readiness.parsers.patches import parse_patches
from coverage_readiness.schema import ClaimedControl, EvidencedControl, Finding


@dataclass
class Assessment:
    business: str
    carrier: str
    as_of: date
    claims: list[ClaimedControl]
    evidence: list[EvidencedControl]
    findings: list[Finding]
    llm_calls: list[dict[str, Any]]  # run-log records written during this assessment


def load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def gather_evidence(
    business_dir: Path, client: LLMClient, log: RunLog, as_of: date
) -> list[EvidencedControl]:
    """Structured exports go through parsers; free text goes through the LLM."""
    return [
        *parse_m365_mfa(business_dir / "m365_mfa.csv"),
        *parse_edr_inventory(business_dir / "edr_inventory.json"),
        *parse_patches(business_dir / "patches.csv", as_of=as_of),
        *read_evidence_notes(client, business_dir / "msp_notes.txt", "msp_notes", as_of, log),
        *read_evidence_notes(client, business_dir / "backup_log.txt", "backup_log", as_of, log),
    ]


def assess(
    business_dir: Path,
    carrier_path: Path,
    client: LLMClient,
    log: RunLog,
    as_of: date,
    application_prompt: str = APPLICATION_PROMPT,
) -> Assessment:
    carrier = load_yaml(carrier_path)
    application = load_yaml(business_dir / f"application_{carrier['carrier']}.yaml")
    calls_before = len(log.read())

    claims = map_application(client, carrier, application, log, application_prompt)
    evidence = gather_evidence(business_dir, client, log, as_of)
    return Assessment(
        business=business_dir.name,
        carrier=carrier["carrier"],
        as_of=as_of,
        claims=claims,
        evidence=evidence,
        findings=compare_all(claims, evidence),
        llm_calls=log.read()[calls_before:],
    )
