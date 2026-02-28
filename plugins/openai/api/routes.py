"""OpenAI runner API routes — model management and Codex CLI auth."""

import asyncio
import os
import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from config.logging_config import logger
from core.api_schemas import ApiResponse, api_error, api_ok
from core.internal_api.auth import verify_internal_auth
from core.registry import get_models_registry
from ui.secrets_manager import secrets_manager

# Strip ANSI escape codes from CLI output
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

router = APIRouter()


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
    """Return current OpenAI model list."""
    registry = get_models_registry()
    if not registry:
        return api_error(503, "Models registry not initialized", "unavailable")
    data = registry.get_metadata("openai")
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
    """Update OpenAI model list manually."""
    registry = get_models_registry()
    if not registry:
        return api_error(503, "Models registry not initialized", "unavailable")
    models = [m.model_dump() for m in request.models]
    registry.set_models("openai", models, source="manual")
    return api_ok(count=len(models))


@router.post(
    "/models/refresh",
    response_model=ApiResponse,
    response_model_exclude_none=True,
)
async def refresh_models(_auth: None = Depends(verify_internal_auth)):
    """Refresh model list from OpenAI API."""
    api_key = secrets_manager.get_plain("OPENAI_API_KEY")
    if not api_key:
        return api_error(400, "OPENAI_API_KEY not configured", "missing_config")

    try:
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()

        # Filter to chat-capable models
        chat_prefixes = ("gpt-", "o1", "o3", "o4", "chatgpt-")
        exclude = ("instruct", "realtime", "audio", "search", "embedding")
        models = []
        for m in data.get("data", []):
            mid = m["id"]
            if not any(mid.startswith(p) for p in chat_prefixes):
                continue
            if any(x in mid for x in exclude):
                continue
            models.append({"id": mid, "name": mid})

        models.sort(key=lambda m: m["id"])

        registry = get_models_registry()
        if registry:
            registry.set_models("openai", models, source="api")
        return api_ok(count=len(models))
    except Exception as e:
        logger.error("OpenAI models refresh error: %s", e)
        return api_error(500, str(e), "internal_error")


# ── Codex CLI Auth ────────────────────────────────────────────────────

_CLI_ENV = {**os.environ, "HOME": "/home/gridbear"}

# Keep a reference to the background login process
_login_proc: asyncio.subprocess.Process | None = None


async def _drain_stdout(proc: asyncio.subprocess.Process) -> None:
    """Keep reading stdout so the process doesn't block on a full pipe."""
    try:
        while True:
            data = await proc.stdout.read(4096)
            if not data:
                break
    except Exception:
        pass


@router.get(
    "/auth/status",
    response_model=ApiResponse[dict],
    response_model_exclude_none=True,
)
async def auth_status(_auth: None = Depends(verify_internal_auth)):
    """Check Codex CLI authentication status."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "codex",
            "login",
            "status",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_CLI_ENV,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        text = stdout.decode(errors="replace").strip()
        logged_in = "logged in" in text.lower() or proc.returncode == 0
        return api_ok(data={"loggedIn": logged_in, "detail": text})
    except FileNotFoundError:
        return api_ok(data={"loggedIn": False, "error": "codex CLI not found"})
    except asyncio.TimeoutError:
        return api_error(504, "Auth status check timed out", "timeout")
    except Exception as e:
        logger.error("Codex auth status error: %s", e)
        return api_error(500, str(e), "internal_error")


@router.post(
    "/auth/logout",
    response_model=ApiResponse,
    response_model_exclude_none=True,
)
async def auth_logout(_auth: None = Depends(verify_internal_auth)):
    """Log out of Codex CLI."""
    global _login_proc
    if _login_proc and _login_proc.returncode is None:
        try:
            _login_proc.kill()
        except ProcessLookupError:
            pass
        _login_proc = None

    try:
        proc = await asyncio.create_subprocess_exec(
            "codex",
            "logout",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_CLI_ENV,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode == 0:
            return api_ok()
        return api_error(
            500,
            stderr.decode(errors="replace").strip()
            or stdout.decode(errors="replace").strip(),
            "cli_error",
        )
    except FileNotFoundError:
        return api_error(500, "codex CLI not found", "cli_not_found")
    except asyncio.TimeoutError:
        return api_error(504, "Logout timed out", "timeout")
    except Exception as e:
        logger.error("Codex auth logout error: %s", e)
        return api_error(500, str(e), "internal_error")


@router.post(
    "/auth/login",
    response_model=ApiResponse[dict],
    response_model_exclude_none=True,
)
async def auth_login(_auth: None = Depends(verify_internal_auth)):
    """Start Codex device-auth login — captures device code and URL.

    The login process is kept alive in the background so the CLI can
    poll for authentication completion after the user enters the code.
    """
    global _login_proc

    # Kill any previous login process
    if _login_proc and _login_proc.returncode is None:
        try:
            _login_proc.kill()
        except ProcessLookupError:
            pass
        _login_proc = None

    try:
        proc = await asyncio.create_subprocess_exec(
            "codex",
            "login",
            "--device-auth",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=_CLI_ENV,
        )
        url = None
        code = None
        output_lines = []
        # Track state: the code appears on the line AFTER "one-time code"
        expect_code_next = False
        try:

            async def _read_lines():
                nonlocal url, code, expect_code_next
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    raw = line.decode(errors="replace").strip()
                    # Strip ANSI escape codes for reliable parsing
                    text = _ANSI_RE.sub("", raw).strip()
                    output_lines.append(text)
                    # Extract URL
                    if "http" in text:
                        for word in text.split():
                            if word.startswith("http"):
                                url = word.rstrip(".")
                    # The device code appears on its own line after "one-time code"
                    if expect_code_next and text:
                        # Device codes look like XXXX-XXXXXX (uppercase alnum + dash)
                        candidate = text.strip()
                        if len(candidate) >= 6 and candidate.replace("-", "").isalnum():
                            code = candidate
                            expect_code_next = False
                    if "one-time code" in text.lower() or "device code" in text.lower():
                        expect_code_next = True
                    # Stop reading once we have both
                    if url and code:
                        break

            await asyncio.wait_for(_read_lines(), timeout=15)
        except asyncio.TimeoutError:
            pass

        if url:
            # Keep process alive and drain stdout in background
            _login_proc = proc
            asyncio.create_task(_drain_stdout(proc))
            return api_ok(data={"url": url, "code": code})

        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return api_error(500, "Could not capture device auth info", "cli_error")
    except FileNotFoundError:
        return api_error(500, "codex CLI not found", "cli_not_found")
    except Exception as e:
        logger.error("Codex auth login error: %s", e)
        return api_error(500, str(e), "internal_error")


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
    """Set up Codex auth using an API key."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "codex",
            "login",
            "--with-api-key",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_CLI_ENV,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=request.api_key.encode()), timeout=30
        )
        if proc.returncode == 0:
            return api_ok()
        return api_error(
            500,
            stderr.decode(errors="replace").strip()
            or stdout.decode(errors="replace").strip(),
            "cli_error",
        )
    except FileNotFoundError:
        return api_error(500, "codex CLI not found", "cli_not_found")
    except asyncio.TimeoutError:
        return api_error(504, "API key setup timed out", "timeout")
    except Exception as e:
        logger.error("Codex API key setup error: %s", e)
        return api_error(500, str(e), "internal_error")
