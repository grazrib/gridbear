"""Hugging Face Inference API runner.

Uses the HF Inference Providers API which supports OpenAI-compatible
/chat/completions endpoint via huggingface.co/api/inference-proxy/{provider}.

For models on HF Hub with inference enabled (Serverless Inference API),
we use the standard HF Inference endpoint directly.
"""

import os
from core.runners.openai_compat import OpenAICompatibleRunner
from ui.secrets_manager import secrets_manager

# Models known to support tool calling via HF Inference
_TOOL_CAPABLE = {
    "meta-llama/Llama-3.3-70B-Instruct",
    "meta-llama/Llama-3.2-3B-Instruct",
    "Qwen/Qwen2.5-72B-Instruct",
    "Qwen/Qwen2.5-Coder-32B-Instruct",
}


class HuggingFaceRunner(OpenAICompatibleRunner):
    """Hugging Face Inference API runner.

    Supports both Serverless Inference API and Inference Providers
    (Together, SambaNova, Fireworks, Nebius, etc.).
    """

    name = "huggingface"

    _DEFAULT_MODELS = [
        {"id": "meta-llama/Llama-3.3-70B-Instruct", "name": "Llama 3.3 70B (tool calling ✓)"},
        {"id": "meta-llama/Llama-3.2-3B-Instruct", "name": "Llama 3.2 3B (fast, tool calling ✓)"},
        {"id": "Qwen/Qwen2.5-72B-Instruct", "name": "Qwen 2.5 72B (tool calling ✓)"},
        {"id": "Qwen/Qwen2.5-Coder-32B-Instruct", "name": "Qwen 2.5 Coder 32B (tool calling ✓)"},
        {"id": "mistralai/Mistral-7B-Instruct-v0.3", "name": "Mistral 7B Instruct"},
        {"id": "google/gemma-2-27b-it", "name": "Gemma 2 27B IT"},
        {"id": "microsoft/phi-4", "name": "Phi-4"},
        {"id": "deepseek-ai/DeepSeek-V3-0324", "name": "DeepSeek V3"},
    ]

    def __init__(self, config: dict):
        # Build base_url from provider setting
        provider = config.get("provider", "auto")
        if provider in ("auto", "serverless", "hf-inference"):
            self.base_url = "https://api-inference.huggingface.co/v1"
        else:
            # Route via inference provider proxy
            self.base_url = f"https://api-inference.huggingface.co/models/dummy"
            # Will be overridden per-provider below
            self.base_url = f"https://router.huggingface.co/{provider}/v1"
        super().__init__(config)
        self._provider = provider

    def _get_api_key(self) -> str:
        return secrets_manager.get_plain("hf_token") or os.getenv("HF_TOKEN", "")

    def _supports_tools(self, model: str) -> bool:
        return model in _TOOL_CAPABLE

    @property
    def available_models(self):
        from core.registry import get_models_registry
        registry = get_models_registry()
        if registry:
            registry.seed_if_empty("huggingface", self._DEFAULT_MODELS)
            models = registry.get_for_ui("huggingface")
            if models:
                return models
        return [(m["id"], m["name"]) for m in self._DEFAULT_MODELS]
