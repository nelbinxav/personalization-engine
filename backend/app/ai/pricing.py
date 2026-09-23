"""Per-model token pricing, so a job can report what it actually cost.

Rates are USD per million tokens, Anthropic first-party API. Cache reads bill
at ~0.1x input and cache writes at ~1.25x input.
"""
from app.models.prospect import Usage

# model id -> (input, output) USD per million tokens
RATES: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.00, 50.00),
    "claude-fable-5": (10.00, 50.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_MULTIPLIER = 1.25

SELECTABLE_MODELS = [
    {"id": "claude-opus-5", "label": "Claude Opus 5 (default)"},
    {"id": "claude-sonnet-5", "label": "Claude Sonnet 5 (cheaper)"},
    {"id": "claude-haiku-4-5", "label": "Claude Haiku 4.5 (cheapest)"},
    {"id": "claude-fable-5-1", "label": "Claude Fable 5.1 (most capable)"},
]


def cost_usd(model: str, usage: Usage) -> float:
    rates = RATES.get(model)
    if not rates:
        # Unknown model: report zero rather than invent a number.
        return 0.0

    input_rate, output_rate = rates
    millions = 1_000_000
    total = (
        usage.input_tokens * input_rate
        + usage.output_tokens * output_rate
        + usage.cache_read_input_tokens * input_rate * CACHE_READ_MULTIPLIER
        + usage.cache_creation_input_tokens * input_rate * CACHE_WRITE_MULTIPLIER
    ) / millions
    return round(total, 6)


def usage_from_response(response) -> Usage:
    raw = getattr(response, "usage", None)
    if raw is None:
        return Usage()
    return Usage(
        input_tokens=getattr(raw, "input_tokens", 0) or 0,
        output_tokens=getattr(raw, "output_tokens", 0) or 0,
        cache_read_input_tokens=getattr(raw, "cache_read_input_tokens", 0) or 0,
        cache_creation_input_tokens=getattr(raw, "cache_creation_input_tokens", 0) or 0,
    )
