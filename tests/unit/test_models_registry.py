"""Tests for core.models_registry.ModelsRegistry."""

import json

import pytest

from core.models_registry import ModelsRegistry


@pytest.fixture
def registry(tmp_path):
    """Create a ModelsRegistry using a temp directory."""
    return ModelsRegistry(base_dir=tmp_path)


class TestModelsRegistry:
    def test_get_models_empty(self, registry):
        assert registry.get_models("claude") == []

    def test_set_and_get_models(self, registry):
        models = [
            {"id": "sonnet", "name": "Sonnet", "api_id": "claude-sonnet-4-5"},
            {"id": "haiku", "name": "Haiku", "api_id": "claude-haiku-4-5"},
        ]
        registry.set_models("claude", models, source="test")
        result = registry.get_models("claude")
        assert len(result) == 2
        assert result[0]["id"] == "sonnet"
        assert result[1]["api_id"] == "claude-haiku-4-5"

    def test_get_for_ui(self, registry):
        models = [
            {"id": "opus", "name": "Opus"},
            {"id": "sonnet", "name": "Sonnet"},
        ]
        registry.set_models("claude", models)
        ui_models = registry.get_for_ui("claude")
        assert ui_models == [("opus", "Opus"), ("sonnet", "Sonnet")]

    def test_get_for_ui_empty(self, registry):
        assert registry.get_for_ui("nonexistent") == []

    def test_get_model_map(self, registry):
        models = [
            {"id": "sonnet", "name": "Sonnet", "api_id": "claude-sonnet-4-5"},
            {"id": "gpt-4o", "name": "GPT-4o"},  # no api_id → uses id
        ]
        registry.set_models("mixed", models)
        model_map = registry.get_model_map("mixed")
        assert model_map == {
            "sonnet": "claude-sonnet-4-5",
            "gpt-4o": "gpt-4o",
        }

    def test_get_metadata(self, registry):
        models = [{"id": "test", "name": "Test"}]
        registry.set_models("runner", models, source="api")
        meta = registry.get_metadata("runner")
        assert meta["source"] == "api"
        assert meta["last_updated"] is not None
        assert len(meta["models"]) == 1

    def test_seed_if_empty_creates(self, registry):
        models = [{"id": "a", "name": "A"}]
        assert registry.seed_if_empty("new_runner", models) is True
        assert registry.get_models("new_runner") == models

    def test_seed_if_empty_skips_existing(self, registry):
        models_v1 = [{"id": "a", "name": "A"}]
        models_v2 = [{"id": "b", "name": "B"}]
        registry.set_models("runner", models_v1)
        assert registry.seed_if_empty("runner", models_v2) is False
        assert registry.get_models("runner") == models_v1  # unchanged

    def test_set_models_overwrites(self, registry):
        registry.set_models("r", [{"id": "a", "name": "A"}])
        registry.set_models("r", [{"id": "b", "name": "B"}])
        assert registry.get_models("r") == [{"id": "b", "name": "B"}]

    def test_runners_independent(self, registry):
        registry.set_models("claude", [{"id": "c", "name": "C"}])
        registry.set_models("openai", [{"id": "o", "name": "O"}])
        assert len(registry.get_models("claude")) == 1
        assert len(registry.get_models("openai")) == 1
        assert registry.get_models("claude")[0]["id"] == "c"

    def test_file_persisted(self, registry, tmp_path):
        registry.set_models("test", [{"id": "x", "name": "X"}])
        path = tmp_path / "test.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["models"][0]["id"] == "x"

    def test_corrupted_file_returns_empty(self, registry, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not json")
        assert registry.get_models("bad") == []
