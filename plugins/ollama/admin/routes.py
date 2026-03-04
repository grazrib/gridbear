"""Ollama plugin admin routes — connection status and model management."""

import os

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from config.logging_config import logger
from ui.jinja_env import templates
from ui.routes.auth import require_login
from ui.routes.plugins import get_plugin_info, get_template_context

router = APIRouter(prefix="/plugins/ollama", tags=["ollama"])

GRIDBEAR_URL = os.getenv("GRIDBEAR_INTERNAL_URL", "http://gridbear:8000")
INTERNAL_SECRET = os.getenv("INTERNAL_API_SECRET", "")


def _get_plugin_metadata() -> dict:
    """Plugin metadata for auto-sidebar."""
    return get_plugin_info("ollama") or {}


async def _fetch_health() -> dict:
    """Proxy health check to the bot's internal API."""
    url = f"{GRIDBEAR_URL}/api/ollama/health"
    headers = {"Authorization": f"Bearer {INTERNAL_SECRET}"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
            data = resp.json()
            if data.get("ok") and data.get("data"):
                return data["data"]
            return {
                "connected": False,
                "host": "unknown",
                "version": None,
                "models": [],
                "configured_model": "unknown",
                "model_available": False,
                "error": data.get("error", "Unexpected response"),
            }
    except httpx.ConnectError:
        return {
            "connected": False,
            "host": "unknown",
            "version": None,
            "models": [],
            "configured_model": "unknown",
            "model_available": False,
            "error": "Bot service unreachable",
        }
    except Exception as exc:
        logger.error("Ollama health proxy error: %s", exc)
        return {
            "connected": False,
            "host": "unknown",
            "version": None,
            "models": [],
            "configured_model": "unknown",
            "model_available": False,
            "error": str(exc),
        }


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def ollama_config_page(request: Request, _: bool = Depends(require_login)):
    """Ollama plugin admin page — status, models, secrets, config."""
    plugin_info = get_plugin_info("ollama")
    if not plugin_info:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Plugin not found")

    health = await _fetch_health()

    return templates.TemplateResponse(
        "plugins/ollama.html",
        get_template_context(
            request,
            plugin=plugin_info,
            plugin_name="ollama",
            health=health,
        ),
    )
