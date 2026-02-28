"""Cost tracking for OpenAI API usage.

Pricing per million tokens (as of 2025-05).
"""

from core.runners.cost_calculator import calculate_cost as _calculate_cost

# Pricing: (model_prefix, input_per_M, output_per_M)
# Order matters: more specific prefixes first (startswith matching)
OPENAI_PRICING: list[tuple[str, float, float]] = [
    ("gpt-5-mini", 0.25, 2.00),
    ("gpt-5", 1.25, 10.00),
    ("gpt-4.1-nano", 0.10, 0.40),
    ("gpt-4.1-mini", 0.40, 1.60),
    ("gpt-4.1", 2.00, 8.00),
    ("gpt-4o-mini", 0.15, 0.60),
    ("gpt-4o", 2.50, 10.00),
    ("o3-pro", 20.00, 80.00),
    ("o3-mini", 1.10, 4.40),
    ("o3", 2.00, 8.00),
    ("o4-mini", 1.10, 4.40),
]


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Calculate USD cost for OpenAI models."""
    return _calculate_cost(model, OPENAI_PRICING, input_tokens, output_tokens)
