"""Cerebras runner — ultra-fast LLM inference via CSX hardware."""

import os
from core.runners.openai_compat import OpenAICompatibleRunner
from ui.secrets_manager import secrets_manager


class CerebrasRunner(OpenAICompatibleRunner):
    """Cerebras cloud runner — up to 2200 tokens/sec, generous free tier."""

    name = "cerebras"
    base_url = "https://api.cerebras.ai/v1"

    _DEFAULT_MODELS = [
        {"id": "llama-3.3-70b", "name": "Llama 3.3 70B (recommended, tool calling ✓)"},
        {"id": "llama-3.1-70b", "name": "Llama 3.1 70B"},
        {"id": "llama-3.1-8b", "name": "Llama 3.1 8B (fastest)"},
        {"id": "qwen-3-32b", "name": "Qwen3 32B"},
    ]

    def _get_api_key(self) -> str:
        return secrets_manager.get_plain("cerebras_api_key") or os.getenv("CEREBRAS_API_KEY", "")

    @property
    def available_models(self):
        from core.registry import get_models_registry
        registry = get_models_registry()
        if registry:
            registry.seed_if_empty("cerebras", self._DEFAULT_MODELS)
            models = registry.get_for_ui("cerebras")
            if models:
                return models
        return [(m["id"], m["name"]) for m in self._DEFAULT_MODELS]
