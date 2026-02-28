"""Tests for Gemini cost tracker."""

from plugins.gemini.cost_tracker import GEMINI_PRICING, calculate_cost


class TestCalculateCost:
    """Tests for calculate_cost()."""

    def test_flash_model(self):
        """gemini-2.0-flash: $0.10/M input, $0.40/M output."""
        cost = calculate_cost("gemini-2.0-flash", 1_000_000, 1_000_000)
        assert cost == 0.10 + 0.40

    def test_flash_lite_model(self):
        """gemini-2.0-flash-lite is free (matches before flash)."""
        cost = calculate_cost("gemini-2.0-flash-lite", 1_000_000, 1_000_000)
        assert cost == 0.0

    def test_pro_model(self):
        """gemini-2.5-pro: $1.25/M input, $10.00/M output."""
        cost = calculate_cost("gemini-2.5-pro", 1_000_000, 1_000_000)
        assert cost == 1.25 + 10.00

    def test_flash_25_model(self):
        """gemini-2.5-flash: $0.15/M input, $0.60/M output."""
        cost = calculate_cost("gemini-2.5-flash", 500_000, 200_000)
        expected = 500_000 * 0.15 / 1_000_000 + 200_000 * 0.60 / 1_000_000
        assert abs(cost - expected) < 1e-10

    def test_small_usage(self):
        """Small token counts produce small costs."""
        cost = calculate_cost("gemini-2.0-flash", 100, 50)
        expected = 100 * 0.10 / 1_000_000 + 50 * 0.40 / 1_000_000
        assert abs(cost - expected) < 1e-10

    def test_zero_tokens(self):
        """Zero tokens means zero cost."""
        cost = calculate_cost("gemini-2.0-flash", 0, 0)
        assert cost == 0.0

    def test_unknown_model(self):
        """Unknown model returns 0.0."""
        cost = calculate_cost("unknown-model-xyz", 1_000_000, 1_000_000)
        assert cost == 0.0

    def test_model_variant_matches_prefix(self):
        """Model variants (e.g. with -exp suffix) match by prefix."""
        cost = calculate_cost("gemini-2.0-flash-exp", 1_000_000, 0)
        # Matches "gemini-2.0-flash" prefix
        assert cost == 0.10

    def test_pricing_list_not_empty(self):
        """Sanity: pricing list has entries."""
        assert len(GEMINI_PRICING) > 0

    def test_flash_lite_before_flash_in_pricing(self):
        """flash-lite must come before flash to match correctly."""
        prefixes = [p[0] for p in GEMINI_PRICING]
        lite_idx = prefixes.index("gemini-2.0-flash-lite")
        flash_idx = prefixes.index("gemini-2.0-flash")
        assert lite_idx < flash_idx, "flash-lite must be checked before flash"
