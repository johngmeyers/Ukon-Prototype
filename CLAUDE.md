# CLAUDE.md

coverage-readiness compares a business's cyber insurance application answers against its MSP's evidence and produces a per-control readiness report.

## Stack
- Python 3.12, managed with uv (`uv sync`, `uv run ...`).
- Pydantic v2 for every model crossing a boundary (LLM output, parsed evidence, findings).
- pytest for tests, ruff for lint and format.
- Anthropic SDK for the LLM; Typer for the CLI.

## Commands
- `uv run coverage-readiness check fixtures/businesses/acme_dental --carrier carrier_a` — readiness report (calls the API; logs to `runs/`)
- `uv run pytest` — unit tests (live tests excluded by default)
- `uv run pytest -m live` — the live API test; reads ANTHROPIC_API_KEY from `.env` (see `.env.example`)
- `uv run ruff check . && uv run ruff format --check .`

## Rules
- No network in unit tests. Use the fake LLM client; anything that calls the API is marked `@pytest.mark.live`.
- The LLM only maps free text to canonical fields. Parsing structured exports and comparing claims vs. evidence are deterministic code.
- Never auto-resolve a low-confidence or conflicting field; it goes to needs_review.
- Prompts live in `src/coverage_readiness/llm/prompts/` as versioned files (`*_v1.md`), never inline.
- Tests ship in the same PR as the code they cover.
- Commits follow Conventional Commits (feat:, fix:, test:, eval:, docs:, chore:). One concern per PR.
- All data is synthetic. Never add real customer or carrier data.
