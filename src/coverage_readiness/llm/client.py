"""LLM client protocol, the Anthropic implementation, a fake for tests, and the run log.

`call_structured` is the only way the rest of the code talks to a model: it sends a
schema-constrained request, validates the reply with Pydantic, retries once with the
validation error, logs every attempt, and raises if the second attempt also fails.
"""

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import anthropic
from pydantic import BaseModel, ValidationError

from coverage_readiness import config


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    stop_reason: str | None


class LLMClient(Protocol):
    def complete(self, *, system: str, user: str, schema: dict[str, Any]) -> LLMResponse: ...


class AnthropicClient:
    """Claude via the Messages API, with output constrained to a JSON schema."""

    def __init__(self, model: str = config.MODEL, client: anthropic.Anthropic | None = None):
        self.model = model
        self._client = client or anthropic.Anthropic()

    def complete(self, *, system: str, user: str, schema: dict[str, Any]) -> LLMResponse:
        start = time.perf_counter()
        response = self._client.beta.messages.create(
            model=self.model,
            max_tokens=config.MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={
                "effort": config.EFFORT,
                "format": {"type": "json_schema", "schema": schema},
            },
            # If a safety classifier declines, the API retries on a fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        latency_ms = round((time.perf_counter() - start) * 1000)
        text = next((b.text for b in response.content if b.type == "text"), "")
        return LLMResponse(
            text=text,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            latency_ms=latency_ms,
            stop_reason=response.stop_reason,
        )


@dataclass
class FakeLLMClient:
    """Returns canned replies in order and records every request. For tests and evals."""

    replies: list[str | LLMResponse]
    model: str = "fake-model"
    calls: list[dict[str, Any]] = field(default_factory=list)

    def complete(self, *, system: str, user: str, schema: dict[str, Any]) -> LLMResponse:
        self.calls.append({"system": system, "user": user, "schema": schema})
        if not self.replies:
            raise AssertionError("FakeLLMClient ran out of canned replies")
        reply = self.replies.pop(0)
        if isinstance(reply, LLMResponse):
            return reply
        return LLMResponse(
            text=reply,
            model=self.model,
            input_tokens=1000,
            output_tokens=200,
            latency_ms=5,
            stop_reason="end_turn",
        )


class RunLog:
    """Appends one JSON line per LLM call: model, prompt version, tokens, cost, latency."""

    def __init__(self, path: Path):
        self.path = path

    def write(self, record: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line]


@dataclass(frozen=True)
class Prompt:
    version: str  # file stem, e.g. "map_application_v1"
    system: str


class LLMOutputError(RuntimeError):
    """The model did not produce valid output, even after one retry."""


def call_structured[T: BaseModel](
    client: LLMClient,
    *,
    prompt: Prompt,
    user: str,
    output_model: type[T],
    log: RunLog,
    context: dict[str, Any] | None = None,
) -> T:
    """One schema-constrained call, validated by Pydantic, with exactly one retry."""
    schema = anthropic.transform_schema(output_model)
    errors: list[str] = []
    for attempt in (1, 2):
        message = user
        if errors:
            message += (
                "\n\nYour previous reply failed validation. Fix this and reply again:\n"
                + errors[-1]
            )
        response = client.complete(system=prompt.system, user=message, schema=schema)
        result, error = _validate(response, output_model, context)
        _log_attempt(log, prompt, response, attempt, error)
        if result is not None:
            return result
        if response.stop_reason in NOT_RETRYABLE:
            raise LLMOutputError(f"{prompt.version}: {error}")
        errors.append(error)
    raise LLMOutputError(f"{prompt.version}: invalid output after retry: {errors[-1]}")


# A refused or truncated reply will fail the same way again, so don't spend a retry on it.
NOT_RETRYABLE = ("refusal", "max_tokens")


def _validate[T: BaseModel](
    response: LLMResponse, output_model: type[T], context: dict[str, Any] | None
) -> tuple[T | None, str | None]:
    if response.stop_reason in NOT_RETRYABLE:
        return None, f"stop_reason={response.stop_reason}"
    try:
        return output_model.model_validate_json(response.text, context=context), None
    except ValidationError as e:
        return None, str(e)


def _log_attempt(
    log: RunLog, prompt: Prompt, response: LLMResponse, attempt: int, error: str | None
) -> None:
    log.write(
        {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "prompt_version": prompt.version,
            "model": response.model,
            "attempt": attempt,
            "ok": error is None,
            "error": error,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "cost_usd": config.cost_usd(
                response.model, response.input_tokens, response.output_tokens
            ),
            "latency_ms": response.latency_ms,
            "stop_reason": response.stop_reason,
        }
    )
