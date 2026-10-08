"""Run the labeled scenarios through the real pipeline and score them.

    uv run python evals/run_evals.py --runs 2

Scores two places so a parsing miss can be told apart from a rule miss:
  - mapping: the claim value the LLM extracted from the application, per field
  - status: the final finding per control
Writes evals/results/<date>-<label>.json and .md.
"""

import json
import shutil
import statistics
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from dotenv import load_dotenv

from coverage_readiness import config
from coverage_readiness.llm.client import AnthropicClient, LLMClient, RunLog
from coverage_readiness.llm.mapper import APPLICATION_PROMPT, NOTES_PROMPT
from coverage_readiness.pipeline import Assessment, assess
from coverage_readiness.schema import ControlId, FindingStatus

ROOT = Path(__file__).parent.parent
SCENARIOS = ROOT / "evals" / "scenarios"
RESULTS = ROOT / "evals" / "results"
FIXTURES = ROOT / "fixtures"
AS_OF = date(2026, 9, 30)  # fixed so "restore tested in the last 12 months" never drifts
UNSCORED = "unscored"
ERROR = "error"


# --- Scenarios ---------------------------------------------------------------


@dataclass
class Scenario:
    id: str
    description: str
    category: str
    base: str
    carrier: str
    answers: dict[str, str]
    expected_claims: dict[str, Any]  # control id -> value, None, or UNSCORED
    expected_status: dict[str, str]  # control id -> FindingStatus value
    dir: Path


def load_scenarios(root: Path = SCENARIOS) -> list[Scenario]:
    bases = yaml.safe_load((root / "bases.yaml").read_text())
    scenarios = []
    for path in sorted(root.glob("*/scenario.yaml")):
        spec = yaml.safe_load(path.read_text())
        base = bases[spec["base"]]
        expected = spec.get("expected", {})
        scenarios.append(
            Scenario(
                id=path.parent.name,
                description=spec["description"],
                category=spec["category"],
                base=spec["base"],
                carrier=spec["carrier"],
                answers={str(k): str(v) for k, v in spec.get("answers", {}).items()},
                expected_claims={**base["claims"], **expected.get("claims", {})},
                expected_status={**base["status"], **expected.get("status", {})},
                dir=path.parent,
            )
        )
    return scenarios


def materialize(scenario: Scenario, dest: Path) -> Path:
    """Base business files, then answer overrides, then any evidence files in the scenario."""
    business = dest / scenario.id
    shutil.copytree(FIXTURES / "businesses" / scenario.base, business)
    app_path = business / f"application_{scenario.carrier}.yaml"
    application = yaml.safe_load(app_path.read_text())
    application["business"] = scenario.id
    for answer in application["answers"]:
        if answer["question_id"] in scenario.answers:
            answer["answer"] = scenario.answers[answer["question_id"]]
    app_path.write_text(yaml.safe_dump(application, sort_keys=False, allow_unicode=True))
    for override in scenario.dir.iterdir():
        if override.name != "scenario.yaml":
            shutil.copy(override, business / override.name)
    return business


# --- Scoring -----------------------------------------------------------------


def same_value(expected: Any, got: Any) -> bool:
    """True == 1 in Python; a claim of `true` must not match 1 day."""
    return type(expected) is type(got) and expected == got


def score_scenario(scenario: Scenario, assessment: Assessment | None, error: str | None) -> dict:
    """Per-control expected vs. predicted for one scenario run."""
    claims = {c.control_id.value: c for c in assessment.claims} if assessment else {}
    findings = {f.control_id.value: f for f in assessment.findings} if assessment else {}
    controls = []
    for cid in (c.value for c in ControlId):
        claim, finding = claims.get(cid), findings.get(cid)
        expected_claim = scenario.expected_claims[cid]
        controls.append(
            {
                "control_id": cid,
                "expected_claim": expected_claim,
                "claim": claim.value if claim else ERROR,
                "claim_confidence": claim.confidence if claim else None,
                "claim_ok": None
                if expected_claim == UNSCORED
                else bool(claim) and same_value(expected_claim, claim.value),
                "expected_status": scenario.expected_status[cid],
                "status": finding.status.value if finding else ERROR,
                "status_ok": bool(finding) and finding.status == scenario.expected_status[cid],
                "reason": finding.reason if finding else error,
            }
        )
    calls = assessment.llm_calls if assessment else []
    return {
        "scenario": scenario.id,
        "category": scenario.category,
        "error": error,
        "controls": controls,
        "llm_calls": len(calls),
        "retries": sum(c["attempt"] > 1 for c in calls),
        "input_tokens": sum(c["input_tokens"] for c in calls),
        "output_tokens": sum(c["output_tokens"] for c in calls),
        "cost_usd": sum(c["cost_usd"] or 0 for c in calls),
        "latency_ms": sum(c["latency_ms"] for c in calls),
    }


def ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1)))]


def metrics(scored: list[dict]) -> dict:
    """Aggregate metrics for one run over all scenarios."""
    rows = [c for s in scored for c in s["controls"]]
    mapped = [c for c in rows if c["claim_ok"] is not None]
    contradicted = FindingStatus.CONTRADICTED.value
    review = FindingStatus.NEEDS_REVIEW.value
    expected_contra = [c for c in rows if c["expected_status"] == contradicted]
    predicted_contra = [c for c in rows if c["status"] == contradicted]

    per_field = {}
    for cid in (c.value for c in ControlId):
        field_rows = [c for c in mapped if c["control_id"] == cid]
        per_field[cid] = ratio(sum(c["claim_ok"] for c in field_rows), len(field_rows))

    per_category = {}
    for category in sorted({s["category"] for s in scored}):
        cat_rows = [c for s in scored if s["category"] == category for c in s["controls"]]
        per_category[category] = ratio(sum(c["status_ok"] for c in cat_rows), len(cat_rows))

    latencies = [s["latency_ms"] for s in scored if not s["error"]]
    return {
        "scenarios": len(scored),
        "errors": sum(bool(s["error"]) for s in scored),
        "mapping_accuracy": ratio(sum(c["claim_ok"] for c in mapped), len(mapped)),
        "mapping_accuracy_per_field": per_field,
        "status_accuracy": ratio(sum(c["status_ok"] for c in rows), len(rows)),
        "status_accuracy_per_category": per_category,
        "contradiction_recall": ratio(
            sum(c["status"] == contradicted for c in expected_contra), len(expected_contra)
        ),
        "contradiction_precision": ratio(
            sum(c["expected_status"] == contradicted for c in predicted_contra),
            len(predicted_contra),
        ),
        # A real gap routed to a human is not missed, just not auto-decided.
        "gap_caught_rate": ratio(
            sum(c["status"] in (contradicted, review) for c in expected_contra),
            len(expected_contra),
        ),
        "review_rate": ratio(sum(c["status"] == review for c in rows), len(rows)),
        "llm_calls": sum(s["llm_calls"] for s in scored),
        "retries": sum(s["retries"] for s in scored),
        "input_tokens": sum(s["input_tokens"] for s in scored),
        "output_tokens": sum(s["output_tokens"] for s in scored),
        "cost_usd": round(sum(s["cost_usd"] for s in scored), 4),
        "cost_per_application_usd": round(statistics.mean(s["cost_usd"] for s in scored), 4),
        "latency_per_application_ms": {
            "p50": percentile(latencies, 50),
            "p95": percentile(latencies, 95),
        },
    }


def failures(scored: list[dict]) -> list[dict]:
    out = []
    for s in scored:
        for c in s["controls"]:
            if c["claim_ok"] is False:
                out.append({"scenario": s["scenario"], "control_id": c["control_id"],
                            "kind": "mapping", "expected": c["expected_claim"],
                            "got": c["claim"], "confidence": c["claim_confidence"]})  # fmt: skip
            if not c["status_ok"]:
                out.append({"scenario": s["scenario"], "control_id": c["control_id"],
                            "kind": "status", "expected": c["expected_status"],
                            "got": c["status"], "reason": c["reason"]})  # fmt: skip
    return out


def stability(runs: list[list[dict]]) -> float | None:
    """Share of scenario x control statuses identical across every run."""
    if len(runs) < 2:
        return None
    keyed = [{(s["scenario"], c["control_id"]): c["status"] for s in run for c in s["controls"]}
             for run in runs]  # fmt: skip
    keys = keyed[0].keys()
    return ratio(sum(len({k[key] for k in keyed}) == 1 for key in keys), len(keys))


# --- Running -----------------------------------------------------------------


def run_once(
    scenarios: list[Scenario],
    client: LLMClient,
    log_dir: Path,
    workers: int,
    application_prompt: str = APPLICATION_PROMPT,
) -> list[dict]:
    with tempfile.TemporaryDirectory() as tmp:

        def one(scenario: Scenario) -> dict:
            business = materialize(scenario, Path(tmp))
            log = RunLog(log_dir / f"{scenario.id}.jsonl")
            carrier = FIXTURES / "carriers" / f"{scenario.carrier}.yaml"
            try:
                assessment = assess(business, carrier, client, log, AS_OF, application_prompt)
                return score_scenario(scenario, assessment, None)
            except Exception as e:  # a crashed scenario is scored as wrong, not fatal
                return score_scenario(scenario, None, f"{type(e).__name__}: {e}")

        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(one, scenarios))


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def render_markdown(result: dict) -> str:
    runs = result["runs"]
    names = [f"Run {i + 1}" for i in range(len(runs))]
    m = [r["metrics"] for r in runs]

    def row(label, values):
        return f"| {label} | " + " | ".join(values) + " |"

    meta = result["meta"]
    lines = [
        f"# Eval results: {meta['label']} ({meta['date']})",
        "",
        f"{meta['scenarios']} scenarios × {len(runs)} runs · model `{meta['model']}` · "
        f"prompts `{meta['prompts']['application']}`, `{meta['prompts']['notes']}` · "
        f"as-of {meta['as_of']}",
        "",
        "| Metric | " + " | ".join(names) + " |",
        "|---|" + "---|" * len(runs),
        row("Mapping accuracy (fields)", [pct(x["mapping_accuracy"]) for x in m]),
        row("Status accuracy", [pct(x["status_accuracy"]) for x in m]),
        row("Contradiction recall", [pct(x["contradiction_recall"]) for x in m]),
        row("Contradiction precision", [pct(x["contradiction_precision"]) for x in m]),
        row("Gaps caught (contradicted or review)", [pct(x["gap_caught_rate"]) for x in m]),
        row("Review rate", [pct(x["review_rate"]) for x in m]),
        row("Scenario errors", [str(x["errors"]) for x in m]),
        row("LLM calls (retries)", [f"{x['llm_calls']} ({x['retries']})" for x in m]),
        row("Tokens in / out", [f"{x['input_tokens']:,} / {x['output_tokens']:,}" for x in m]),
        row("Cost total", [f"${x['cost_usd']:.2f}" for x in m]),
        row("Cost per application", [f"${x['cost_per_application_usd']:.3f}" for x in m]),
        row(
            "Latency per application p50 / p95",
            [
                f"{x['latency_per_application_ms']['p50'] / 1000:.1f}s / "
                f"{x['latency_per_application_ms']['p95'] / 1000:.1f}s"
                for x in m
            ],
        ),  # fmt: skip
        "",
        f"Status stability across runs: {pct(result['stability'])}",
        "",
        "## Status accuracy by category",
        "",
        "| Category | " + " | ".join(names) + " |",
        "|---|" + "---|" * len(runs),
    ]
    for cat in m[0]["status_accuracy_per_category"]:
        lines.append(row(cat, [pct(x["status_accuracy_per_category"][cat]) for x in m]))
    lines += [
        "",
        "## Mapping accuracy by field",
        "",
        "| Field | " + " | ".join(names) + " |",
        "|---|" + "---|" * len(runs),
    ]
    for cid in m[0]["mapping_accuracy_per_field"]:
        lines.append(row(f"`{cid}`", [pct(x["mapping_accuracy_per_field"][cid]) for x in m]))
    for i, run in enumerate(runs):
        lines += ["", f"## Failures, run {i + 1}", ""]
        if not run["failures"]:
            lines.append("None.")
            continue
        lines += [
            "| Scenario | Control | Kind | Expected | Got | Detail |",
            "|---|---|---|---|---|---|",
        ]
        for f in run["failures"]:
            detail = (
                f"conf {f['confidence']:.2f}"
                if f["kind"] == "mapping" and f["confidence"] is not None
                else (f.get("reason") or "")
            )
            detail = str(detail).replace("|", "\\|")
            lines.append(
                f"| {f['scenario']} | `{f['control_id']}` | {f['kind']} | "
                f"{json.dumps(f['expected'])} | {json.dumps(f['got'])} | {detail} |"
            )
    return "\n".join(lines) + "\n"


def main(
    runs: Annotated[int, typer.Option(help="How many times to run the full set.")] = 2,
    workers: Annotated[int, typer.Option(help="Scenarios run in parallel.")] = 4,
    label: Annotated[str | None, typer.Option(help="Results name; default from prompt.")] = None,
    only: Annotated[str | None, typer.Option(help="Run scenarios whose id contains this.")] = None,
    application_prompt: Annotated[
        str, typer.Option(help="Prompt file stem, e.g. map_application_v1 to rerun the baseline.")
    ] = APPLICATION_PROMPT,
) -> None:
    load_dotenv()
    scenarios = [s for s in load_scenarios() if not only or only in s.id]
    label = label or application_prompt.rsplit("_", 1)[-1]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    client = AnthropicClient()

    all_runs = []
    for i in range(runs):
        typer.echo(f"Run {i + 1}/{runs}: {len(scenarios)} scenarios...")
        log_dir = ROOT / "runs" / "evals" / stamp / f"run{i + 1}"
        scored = run_once(scenarios, client, log_dir, workers, application_prompt)
        all_runs.append(scored)
        m = metrics(scored)
        typer.echo(
            f"  status {pct(m['status_accuracy'])} · mapping {pct(m['mapping_accuracy'])} · "
            f"recall {pct(m['contradiction_recall'])} · ${m['cost_usd']:.2f}"
        )

    result = {
        "meta": {
            "label": label,
            "date": date.today().isoformat(),
            "model": config.MODEL,
            "effort": config.EFFORT,
            "prompts": {"application": application_prompt, "notes": NOTES_PROMPT},
            "thresholds": config.THRESHOLDS,
            "as_of": AS_OF.isoformat(),
            "scenarios": len(scenarios),
        },
        "stability": stability(all_runs),
        "runs": [
            {"metrics": metrics(scored), "failures": failures(scored), "scenarios": scored}
            for scored in all_runs
        ],
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    name = f"{date.today().isoformat()}-{label}"
    (RESULTS / f"{name}.json").write_text(json.dumps(result, indent=2) + "\n")
    (RESULTS / f"{name}.md").write_text(render_markdown(result))
    typer.echo(f"Wrote evals/results/{name}.json and .md")


if __name__ == "__main__":
    typer.run(main)
