"""Cost tracking for Gemini API usage.

Pricing per million tokens (as of 2025-02).
"""

from core.runners.cost_calculator import calculate_cost as _calculate_cost

# Pricing: (model_prefix, input_per_M, output_per_M)
# Order matters: more specific prefixes first (startswith matching)
GEMINI_PRICING: list[tuple[str, float, float]] = [
    ("gemini-2.0-flash-lite", 0.0, 0.0),  # Free tier
    ("gemini-2.0-flash", 0.10, 0.40),
    ("gemini-2.5-flash", 0.15, 0.60),
    ("gemini-2.5-pro", 1.25, 10.00),
    ("gemini-2.0-pro", 1.25, 10.00),
    ("gemini-1.5-flash", 0.075, 0.30),
    ("gemini-1.5-pro", 1.25, 5.00),
]


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Calculate USD cost for Gemini models."""
    return _calculate_cost(model, GEMINI_PRICING, input_tokens, output_tokens)
