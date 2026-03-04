"""Cost tracking for Mistral API usage.

Pricing per million tokens (as of 2025-05).
CLI backend (Le Chat subscription) reports cost as $0.0.
"""

from core.runners.cost_calculator import calculate_cost as _calculate_cost

# Pricing: (model_prefix, input_per_M, output_per_M)
# Order matters: more specific prefixes first (startswith matching)
MISTRAL_PRICING: list[tuple[str, float, float]] = [
    ("mistral-large", 0.50, 1.50),
    ("mistral-medium", 0.40, 2.00),
    ("mistral-small-3.2", 0.06, 0.18),
    ("mistral-small", 0.05, 0.08),
    ("devstral-2", 0.40, 2.00),
    ("devstral-small", 0.10, 0.30),
    ("codestral", 0.30, 0.90),
    ("ministral-3-14b", 0.20, 0.20),
    ("ministral-3-8b", 0.15, 0.15),
    ("ministral-3-3b", 0.10, 0.10),
    ("pixtral-large", 2.00, 6.00),
    ("pixtral", 0.10, 0.30),
    ("mistral-nemo", 0.02, 0.04),
]


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Calculate USD cost for Mistral models."""
    return _calculate_cost(model, MISTRAL_PRICING, input_tokens, output_tokens)
