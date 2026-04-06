"""DeepSeek runner — high-capability models at ultra-low cost."""

import os
from core.runners.openai_compat import OpenAICompatibleRunner
from ui.secrets_manager import secrets_manager


# deepseek-reasoner does NOT support tool calling
_TOOL_MODELS = {"deepseek-chat"}


class DeepSeekRunner(OpenAICompatibleRunner):
    """DeepSeek cloud runner — cheap, capable, supports function calling."""

    name = "deepseek"
    base_url = "https://api.deepseek.com"

    _DEFAULT_MODELS = [
        {"id": "deepseek-chat", "name": "DeepSeek Chat V3 (tool calling ✓)"},
        {"id": "deepseek-reasoner", "name": "DeepSeek R1 Reasoner (no tools)"},
    ]

    def _get_api_key(self) -> str:
        return secrets_manager.get_plain("deepseek_api_key") or os.getenv("DEEPSEEK_API_KEY", "")

    def _supports_tools(self, model: str) -> bool:
        return model in _TOOL_MODELS

    @property
    def available_models(self):
        from core.registry import get_models_registry
        registry = get_models_registry()
        if registry:
            registry.seed_if_empty("deepseek", self._DEFAULT_MODELS)
            models = registry.get_for_ui("deepseek")
            if models:
                return models
        return [(m["id"], m["name"]) for m in self._DEFAULT_MODELS]
