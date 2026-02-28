"""Cost tracking for Ollama — always $0.0 (local inference)."""


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Return 0.0 — Ollama runs locally, no per-token cost."""
    return 0.0
