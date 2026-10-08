"""Settings for LLM calls. Change the model here, never inline."""

MODEL = "claude-opus-5-5"
# Opus 5.5 rejects `temperature` and forced `tool_choice`; schema-constrained output plus
# Pydantic validation is how we get consistent, typed results instead.
EFFORT = "medium"
MAX_TOKENS = 16000

# Models that support the API's server-side refusal fallback. Claude Haiku 5.5 does not.
SERVER_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}

# USD per million tokens (input, output). Anthropic list prices as of PRICES_AS_OF.
# A refusal fallback can route to another model, so price every model it might use.
PRICES_AS_OF = "2026-10-06"
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),  # prompts up to 100K tokens; ours are ~3K
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Estimated cost of one call, or None if the model has no price on file."""
    prices = PRICES_PER_MTOK.get(model)
    if prices is None:
        return None
    return (input_tokens * prices[0] + output_tokens * prices[1]) / 1_000_000


# Comparison policy. Every judgment threshold lives here so it can be tuned in one place.
THRESHOLDS = {
    # Claims or LLM-read evidence below this confidence go to a human, whatever they say.
    "min_confidence": 0.8,
    # Share of endpoints that must be covered for "on all endpoints" to be true.
    "full_coverage": 1.0,
}
