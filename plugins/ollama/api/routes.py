"""Ollama runner API routes — model management."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from config.logging_config import logger
from core.api_schemas import ApiResponse, api_error, api_ok
from core.internal_api.auth import verify_internal_auth
from core.registry import get_models_registry

router = APIRouter()


class ModelEntry(BaseModel):
    id: str
    name: str
    api_id: str | None = None


class SetModelsRequest(BaseModel):
    models: list[ModelEntry]


@router.get(
    "/models",
    response_model=ApiResponse[dict],
    response_model_exclude_none=True,
)
async def get_models(_auth: None = Depends(verify_internal_auth)):
    """Return current Ollama model list."""
    registry = get_models_registry()
    if not registry:
        return api_error(503, "Models registry not initialized", "unavailable")
    data = registry.get_metadata("ollama")
    return api_ok(data=data)


@router.post(
    "/models",
    response_model=ApiResponse,
    response_model_exclude_none=True,
)
async def set_models(
    request: SetModelsRequest,
    _auth: None = Depends(verify_internal_auth),
):
    """Update Ollama model list manually."""
    registry = get_models_registry()
    if not registry:
        return api_error(503, "Models registry not initialized", "unavailable")
    models = [m.model_dump() for m in request.models]
    registry.set_models("ollama", models, source="manual")
    return api_ok(count=len(models))


@router.post(
    "/models/refresh",
    response_model=ApiResponse,
    response_model_exclude_none=True,
)
async def refresh_models(_auth: None = Depends(verify_internal_auth)):
    """Refresh model list from local Ollama instance (/api/tags)."""
    from core.registry import get_plugin_manager

    # Get Ollama host from plugin config
    pm = get_plugin_manager()
    host = "http://ollama:11434"
    if pm:
        ollama = pm.get_service("ollama") or pm.runners.get("ollama")
        if ollama and hasattr(ollama, "host"):
            host = ollama.host

    try:
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{host}/api/tags")
            resp.raise_for_status()
            data = resp.json()

        models = []
        for m in data.get("models", []):
            name = m.get("name", "")
            # Format: "qwen3:8b" → "Qwen3 8B"
            display = name.replace(":", " ").replace("-", " ").title()
            # Add size info if available
            size_gb = m.get("size", 0) / (1024**3)
            if size_gb > 0.1:
                display += f" ({size_gb:.1f} GB)"
            models.append({"id": name, "name": display})

        models.sort(key=lambda m: m["id"])

        registry = get_models_registry()
        if registry:
            registry.set_models("ollama", models, source="api")
        return api_ok(count=len(models))
    except Exception as e:
        logger.error("Ollama models refresh error: %s", e)
        return api_error(500, str(e), "internal_error")
