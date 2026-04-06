"""OpenRouter runner — gateway to 200+ LLMs via a single API."""

import os
from core.runners.openai_compat import OpenAICompatibleRunner
from ui.secrets_manager import secrets_manager


class OpenRouterRunner(OpenAICompatibleRunner):
    """OpenRouter cloud runner — routes to 200+ models, many free."""

    name = "openrouter"
    base_url = "https://openrouter.ai/api/v1"

    _DEFAULT_MODELS = [
        {"id": "meta-llama/llama-3.3-70b-instruct:free", "name": "Llama 3.3 70B (free)"},
        {"id": "deepseek/deepseek-chat:free", "name": "DeepSeek Chat (free)"},
        {"id": "deepseek/deepseek-r1:free", "name": "DeepSeek R1 (free, reasoning)"},
        {"id": "qwen/qwq-32b:free", "name": "Qwen QwQ 32B (free, reasoning)"},
        {"id": "qwen/qwen3-235b-a22b:free", "name": "Qwen3 235B MoE (free)"},
        {"id": "google/gemma-3-27b-it:free", "name": "Gemma 3 27B (free)"},
        {"id": "mistralai/mistral-7b-instruct:free", "name": "Mistral 7B (free)"},
        {"id": "meta-llama/llama-3.2-3b-instruct:free", "name": "Llama 3.2 3B (free, fast)"},
        {"id": "nousresearch/hermes-3-llama-3.1-405b:free", "name": "Hermes 3 405B (free)"},
        {"id": "openai/gpt-4o-mini", "name": "GPT-4o Mini"},
        {"id": "anthropic/claude-3-haiku", "name": "Claude 3 Haiku"},
        {"id": "x-ai/grok-3-mini-beta", "name": "Grok 3 Mini"},
    ]

    def _get_api_key(self) -> str:
        return secrets_manager.get_plain("openrouter_api_key") or os.getenv("OPENROUTER_API_KEY", "")

    def _extra_headers(self) -> dict:
        headers = {}
        site_url = self.config.get("site_url", "")
        site_name = self.config.get("site_name", "GridBear")
        if site_url:
            headers["HTTP-Referer"] = site_url
        if site_name:
            headers["X-Title"] = site_name
        return headers

    @property
    def available_models(self):
        from core.registry import get_models_registry
        registry = get_models_registry()
        if registry:
            registry.seed_if_empty("openrouter", self._DEFAULT_MODELS)
            models = registry.get_for_ui("openrouter")
            if models:
                return models
        return [(m["id"], m["name"]) for m in self._DEFAULT_MODELS]
