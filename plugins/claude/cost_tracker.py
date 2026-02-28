"""Cost tracking for Anthropic Claude API usage.

Pricing per million tokens (as of 2025-06).
"""

from core.runners.cost_calculator import calculate_cost as _calculate_cost

# Pricing: (model_prefix, input_per_M, output_per_M)
# Matching uses startswith() so order matters: more specific prefixes first
CLAUDE_PRICING: list[tuple[str, float, float]] = [
    ("claude-haiku-4", 0.80, 4.00),
    ("claude-sonnet-4", 3.00, 15.00),
    ("claude-opus-4", 15.00, 75.00),
    # Legacy models
    ("claude-3-5-haiku", 0.80, 4.00),
    ("claude-3-5-sonnet", 3.00, 15.00),
    ("claude-3-opus", 15.00, 75.00),
]


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Calculate USD cost for Claude models."""
    return _calculate_cost(model, CLAUDE_PRICING, input_tokens, output_tokens)
