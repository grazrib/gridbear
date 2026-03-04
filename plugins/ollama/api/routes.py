"""Ollama runner API routes — model management and health checks."""

import httpx
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


def _get_ollama_host() -> tuple[str, str]:
    """Return (host, configured_model) from the running Ollama runner."""
    from core.registry import get_plugin_manager

    pm = get_plugin_manager()
    host = "http://ollama:11434"
    model = "qwen3:8b"
    if pm:
        ollama = pm.get_service("ollama") or pm.runners.get("ollama")
        if ollama:
            if hasattr(ollama, "host"):
                host = ollama.host
            if hasattr(ollama, "model"):
                model = ollama.model
    return host, model


@router.get(
    "/health",
    response_model=ApiResponse[dict],
    response_model_exclude_none=True,
)
async def health_check(_auth: None = Depends(verify_internal_auth)):
    """Check Ollama connectivity, version, and installed models."""
    host, configured_model = _get_ollama_host()

    result = {
        "connected": False,
        "host": host,
        "version": None,
        "models": [],
        "configured_model": configured_model,
        "model_available": False,
        "error": None,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Fetch models and version in parallel
            tags_resp = await client.get(f"{host}/api/tags")
            tags_resp.raise_for_status()
            tags_data = tags_resp.json()

            version_str = None
            try:
                ver_resp = await client.get(f"{host}/api/version")
                if ver_resp.status_code == 200:
                    version_str = ver_resp.json().get("version")
            except Exception:
                pass  # version endpoint is optional

        result["connected"] = True
        result["version"] = version_str

        models = []
        for m in tags_data.get("models", []):
            name = m.get("name", "")
            size_gb = round(m.get("size", 0) / (1024**3), 2)
            models.append(
                {
                    "name": name,
                    "size_gb": size_gb,
                    "modified_at": m.get("modified_at", ""),
                }
            )
        models.sort(key=lambda x: x["name"])
        result["models"] = models

        # Check if configured model is available (match with or without tag)
        model_names = [m["name"] for m in models]
        result["model_available"] = (
            configured_model in model_names
            or f"{configured_model}:latest" in model_names
            or any(n.startswith(f"{configured_model}:") for n in model_names)
        )

    except httpx.ConnectError:
        result["error"] = f"Cannot connect to {host}"
    except httpx.TimeoutException:
        result["error"] = f"Timeout connecting to {host}"
    except Exception as e:
        logger.error("Ollama health check error: %s", e)
        result["error"] = str(e)

    return api_ok(data=result)
