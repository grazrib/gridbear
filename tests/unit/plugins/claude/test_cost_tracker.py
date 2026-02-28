"""Tests for Claude cost tracker."""

from plugins.claude.cost_tracker import CLAUDE_PRICING, calculate_cost


class TestCalculateCost:
    """Tests for calculate_cost()."""

    def test_sonnet_model(self):
        """claude-sonnet-4: $3.00/M input, $15.00/M output."""
        cost = calculate_cost("claude-sonnet-4-5-20250929", 1_000_000, 1_000_000)
        assert cost == 3.00 + 15.00

    def test_opus_model(self):
        """claude-opus-4: $15.00/M input, $75.00/M output."""
        cost = calculate_cost("claude-opus-4-5-20250929", 1_000_000, 1_000_000)
        assert cost == 15.00 + 75.00

    def test_haiku_model(self):
        """claude-haiku-4: $0.80/M input, $4.00/M output."""
        cost = calculate_cost("claude-haiku-4-5-20251001", 1_000_000, 1_000_000)
        assert cost == 0.80 + 4.00

    def test_small_usage(self):
        """Small token counts produce small costs."""
        cost = calculate_cost("claude-sonnet-4-5-20250929", 100, 50)
        expected = 100 * 3.00 / 1_000_000 + 50 * 15.00 / 1_000_000
        assert abs(cost - expected) < 1e-10

    def test_zero_tokens(self):
        """Zero tokens means zero cost."""
        cost = calculate_cost("claude-sonnet-4-5-20250929", 0, 0)
        assert cost == 0.0

    def test_unknown_model(self):
        """Unknown model returns 0.0."""
        cost = calculate_cost("unknown-model-xyz", 1_000_000, 1_000_000)
        assert cost == 0.0

    def test_model_variant_matches_prefix(self):
        """Model variants match by prefix."""
        cost = calculate_cost("claude-sonnet-4-6-20260101", 1_000_000, 0)
        assert cost == 3.00

    def test_legacy_sonnet_model(self):
        """claude-3-5-sonnet: $3.00/M input, $15.00/M output."""
        cost = calculate_cost("claude-3-5-sonnet-20241022", 1_000_000, 1_000_000)
        assert cost == 3.00 + 15.00

    def test_legacy_opus_model(self):
        """claude-3-opus: $15.00/M input, $75.00/M output."""
        cost = calculate_cost("claude-3-opus-20240229", 1_000_000, 1_000_000)
        assert cost == 15.00 + 75.00

    def test_pricing_list_not_empty(self):
        """Sanity: pricing list has entries."""
        assert len(CLAUDE_PRICING) > 0

    def test_haiku_before_sonnet_matches_correctly(self):
        """haiku must match before sonnet for claude-haiku-4 models."""
        cost_haiku = calculate_cost("claude-haiku-4-5-20251001", 1_000_000, 0)
        cost_sonnet = calculate_cost("claude-sonnet-4-5-20250929", 1_000_000, 0)
        assert cost_haiku < cost_sonnet
