"""Mistral runner API routes — model management, Vibe CLI auth, health check."""

import asyncio
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from config.logging_config import logger
from core.api_schemas import ApiResponse, api_error, api_ok
from core.internal_api.auth import verify_internal_auth
from core.registry import get_models_registry
from ui.secrets_manager import secrets_manager

router = APIRouter()

VIBE_ENV_PATH = Path.home() / ".vibe" / ".env"


# ── Model management ──────────────────────────────────────────────────


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
    """Return current Mistral model list."""
    registry = get_models_registry()
    if not registry:
        return api_error(503, "Models registry not initialized", "unavailable")
    data = registry.get_metadata("mistral")
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
    """Update Mistral model list manually."""
    registry = get_models_registry()
    if not registry:
        return api_error(503, "Models registry not initialized", "unavailable")
    models = [m.model_dump() for m in request.models]
    registry.set_models("mistral", models, source="manual")
    return api_ok(count=len(models))


@router.post(
    "/models/refresh",
    response_model=ApiResponse,
    response_model_exclude_none=True,
)
async def refresh_models(_auth: None = Depends(verify_internal_auth)):
    """Refresh model list from Mistral API."""
    api_key = secrets_manager.get_plain("MISTRAL_API_KEY")
    if not api_key:
        return api_error(400, "MISTRAL_API_KEY not configured", "missing_config")

    try:
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.mistral.ai/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()

        models = []
        for m in data.get("data", []):
            mid = m.get("id", "")
            # Skip embedding/moderation models
            capabilities = m.get("capabilities", {})
            if capabilities and not capabilities.get("completion_chat", True):
                continue
            display = mid.replace("-", " ").replace("latest", "").strip().title()
            models.append({"id": mid, "name": display or mid})

        models.sort(key=lambda m: m["id"])

        registry = get_models_registry()
        if registry:
            registry.set_models("mistral", models, source="api")
        return api_ok(count=len(models))
    except Exception as e:
        logger.error("Mistral models refresh error: %s", e)
        return api_error(500, str(e), "internal_error")


# ── Vibe CLI Auth ─────────────────────────────────────────────────────


@router.get(
    "/auth/status",
    response_model=ApiResponse[dict],
    response_model_exclude_none=True,
)
async def auth_status(_auth: None = Depends(verify_internal_auth)):
    """Check Vibe CLI authentication status.

    Verifies: 1) API key in secrets manager, 2) key validity via API call,
    3) Vibe CLI binary availability.
    """
    api_key = secrets_manager.get_plain("MISTRAL_API_KEY")
    cli_installed = shutil.which("vibe") is not None

    if not api_key:
        return api_ok(
            data={
                "loggedIn": False,
                "cliInstalled": cli_installed,
                "detail": "No API key configured",
            }
        )

    # Verify key with lightweight API call
    try:
        import httpx

        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                "https://api.mistral.ai/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            valid = resp.status_code == 200
    except Exception:
        valid = False

    return api_ok(
        data={
            "loggedIn": valid,
            "cliInstalled": cli_installed,
            "detail": "API key valid" if valid else "API key invalid or unreachable",
        }
    )


class ApiKeyRequest(BaseModel):
    api_key: str


@router.post(
    "/auth/api-key",
    response_model=ApiResponse,
    response_model_exclude_none=True,
)
async def auth_api_key(
    request: ApiKeyRequest,
    _auth: None = Depends(verify_internal_auth),
):
    """Save Mistral API key to secrets manager and write ~/.vibe/.env."""
    # Save to secrets manager (used by API backend)
    secrets_manager.set("MISTRAL_API_KEY", request.api_key)

    # Write to ~/.vibe/.env (used by Vibe CLI)
    try:
        VIBE_ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
        VIBE_ENV_PATH.write_text(f"MISTRAL_API_KEY={request.api_key}\n")
    except OSError as e:
        logger.warning("Could not write %s: %s", VIBE_ENV_PATH, e)

    return api_ok()


@router.post(
    "/auth/logout",
    response_model=ApiResponse,
    response_model_exclude_none=True,
)
async def auth_logout(_auth: None = Depends(verify_internal_auth)):
    """Remove Mistral API key from secrets manager and ~/.vibe/.env."""
    secrets_manager.delete("MISTRAL_API_KEY")

    try:
        if VIBE_ENV_PATH.exists():
            VIBE_ENV_PATH.unlink()
    except OSError as e:
        logger.warning("Could not remove %s: %s", VIBE_ENV_PATH, e)

    return api_ok()


# ── Health check ──────────────────────────────────────────────────────


@router.get(
    "/health",
    response_model=ApiResponse[dict],
    response_model_exclude_none=True,
)
async def health_check(_auth: None = Depends(verify_internal_auth)):
    """Check Mistral API connectivity and Vibe CLI availability."""
    result = {
        "connected": False,
        "api_key_valid": False,
        "cli_installed": shutil.which("vibe") is not None,
        "cli_version": None,
        "models_count": 0,
        "error": None,
    }

    api_key = secrets_manager.get_plain("MISTRAL_API_KEY")
    if not api_key:
        result["error"] = "MISTRAL_API_KEY not configured"
        return api_ok(data=result)

    try:
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.mistral.ai/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if resp.status_code == 200:
                result["connected"] = True
                result["api_key_valid"] = True
                data = resp.json()
                result["models_count"] = len(data.get("data", []))
            else:
                result["error"] = f"API returned {resp.status_code}"
    except Exception as e:
        result["error"] = str(e)

    # Check CLI version if installed
    if result["cli_installed"]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "vibe",
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            if proc.returncode == 0:
                result["cli_version"] = stdout.decode().strip()
        except Exception:
            pass

    return api_ok(data=result)
