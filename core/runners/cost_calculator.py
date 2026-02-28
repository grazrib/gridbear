"""Shared cost calculation for runner plugins.

Each runner defines a pricing table as list[tuple[str, float, float]]
(model_prefix, input_price_per_M, output_price_per_M). This module
provides the common lookup + arithmetic so individual runners only
need to maintain their pricing data.
"""


def calculate_cost(
    model: str,
    pricing: list[tuple[str, float, float]],
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Calculate USD cost from token usage against a pricing table.

    Args:
        model: Model name (matched via ``startswith``).
        pricing: List of (prefix, input_$/M, output_$/M) — order
                 matters, more specific prefixes should come first.
        input_tokens: Number of input tokens.
        output_tokens: Number of output tokens.

    Returns:
        Cost in USD.  Returns ``0.0`` for unknown models.
    """
    for prefix, input_price, output_price in pricing:
        if model.startswith(prefix):
            return (
                input_tokens * input_price / 1_000_000
                + output_tokens * output_price / 1_000_000
            )
    return 0.0
