"""Gemini runner API routes — model management."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from config.logging_config import logger
from core.api_schemas import ApiResponse, api_error, api_ok
from core.internal_api.auth import verify_internal_auth
from core.registry import get_models_registry
from ui.secrets_manager import secrets_manager

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
    """Return current Gemini model list."""
    registry = get_models_registry()
    if not registry:
        return api_error(503, "Models registry not initialized", "unavailable")
    data = registry.get_metadata("gemini")
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
    """Update Gemini model list manually."""
    registry = get_models_registry()
    if not registry:
        return api_error(503, "Models registry not initialized", "unavailable")
    models = [m.model_dump() for m in request.models]
    registry.set_models("gemini", models, source="manual")
    return api_ok(count=len(models))


@router.post(
    "/models/refresh",
    response_model=ApiResponse,
    response_model_exclude_none=True,
)
async def refresh_models(_auth: None = Depends(verify_internal_auth)):
    """Refresh model list from Google AI API."""
    api_key = secrets_manager.get_plain("GOOGLE_AI_API_KEY")
    if not api_key:
        return api_error(400, "GOOGLE_AI_API_KEY not configured", "missing_config")

    try:
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                params={"key": api_key},
            )
            resp.raise_for_status()
            data = resp.json()

        models = []
        for m in data.get("models", []):
            # name format: "models/gemini-2.5-flash"
            model_id = m.get("name", "").removeprefix("models/")
            if not model_id.startswith("gemini"):
                continue
            # Filter: only generateContent-capable models
            methods = m.get("supportedGenerationMethods", [])
            if "generateContent" not in methods:
                continue
            display = m.get("displayName", model_id)
            models.append({"id": model_id, "name": display})

        models.sort(key=lambda m: m["id"])

        registry = get_models_registry()
        if registry:
            registry.set_models("gemini", models, source="api")
        return api_ok(count=len(models))
    except Exception as e:
        logger.error("Gemini models refresh error: %s", e)
        return api_error(500, str(e), "internal_error")
