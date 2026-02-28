"""HTTP chat proxy for CLI and external clients.

Accepts a chat message, forwards it to gridbear:8000/api/chat via
INTERNAL_API_SECRET, collects the full NDJSON response, and returns
the final message text synchronously.

Auth: OAuth2 Bearer token (scope: api) OR INTERNAL_API_SECRET.
"""

import hmac
import json
import os

import aiohttp
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from config.logging_config import logger
from core.api_schemas import api_error, api_ok

router = APIRouter()

GRIDBEAR_URL = os.getenv("GRIDBEAR_INTERNAL_URL", "http://gridbear:8000")
GRIDBEAR_SECRET = os.getenv("INTERNAL_API_SECRET", "")


def _authenticate(request: Request) -> dict | JSONResponse:
    """Validate Bearer token — OAuth2 or INTERNAL_API_SECRET.

    Returns user info dict on success, or JSONResponse error.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return api_error(401, "Bearer token required", "auth_error")

    token_string = auth_header[7:]

    # Try INTERNAL_API_SECRET first (fast path)
    if GRIDBEAR_SECRET and hmac.compare_digest(token_string, GRIDBEAR_SECRET):
        return {"auth_type": "internal"}

    # Try OAuth2 token
    from core.oauth2.server import get_db

    db = get_db()
    token, client = db.validate_token(token_string)

    if not token or not token.is_valid():
        return api_error(401, "Invalid or expired token", "auth_error")

    scopes = set(token.scope.split()) if token.scope else set()
    if "api" not in scopes:
        return api_error(403, "Scope 'api' required", "auth_error")

    return {
        "auth_type": "oauth2",
        "client": client,
        "agent_name": client.agent_name if client else None,
    }


@router.post("/api/proxy/chat")
async def proxy_chat(request: Request):
    """Forward a chat message to the gridbear container and return the response.

    Request body:
        {
            "text": "message text",
            "user_id": "unified_id",
            "agent_name": "peggy",
            "username": "optional",
            "display_name": "optional"
        }

    Response:
        {ok: true, data: {text: "response", agent: "agent_name", events: [...]}}
    """
    auth = _authenticate(request)
    if isinstance(auth, JSONResponse):
        return auth

    try:
        body = await request.json()
    except Exception:
        return api_error(400, "Invalid JSON body", "validation_error")

    text = body.get("text", "").strip()
    if not text:
        return api_error(400, "Field 'text' is required", "validation_error")

    user_id = body.get("user_id")
    if not user_id:
        return api_error(400, "Field 'user_id' is required", "validation_error")

    agent_name = body.get("agent_name")
    if not agent_name:
        return api_error(400, "Field 'agent_name' is required", "validation_error")

    payload = {
        "text": text,
        "user_id": user_id,
        "username": body.get("username", user_id),
        "display_name": body.get("display_name", ""),
        "agent_name": agent_name,
    }
    attachments = body.get("attachments")
    if attachments:
        payload["attachments"] = attachments

    if not GRIDBEAR_SECRET:
        return api_error(503, "INTERNAL_API_SECRET not configured", "config_error")

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                f"{GRIDBEAR_URL}/api/chat",
                json=payload,
                headers={"Authorization": f"Bearer {GRIDBEAR_SECRET}"},
                timeout=aiohttp.ClientTimeout(total=600),
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(
                        "Chat proxy: gridbear API error %s: %s", resp.status, error_text
                    )
                    return api_error(
                        502, f"Gridbear API error: {resp.status}", "upstream_error"
                    )

                result_text = ""
                stream_buffer = ""
                events = []

                async for chunk in resp.content:
                    line = chunk.decode().strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    event_type = event.get("type")
                    events.append(event)

                    if event_type == "message":
                        result_text = event.get("text", "")
                    elif event_type == "stream":
                        stream_buffer += event.get("text", "")
                    elif event_type == "stream_end":
                        if stream_buffer and not result_text:
                            result_text = stream_buffer
                    elif event_type == "error":
                        return api_error(
                            500,
                            event.get("details", "Agent error"),
                            event.get("error_type", "agent_error"),
                        )

                return api_ok(
                    {"text": result_text, "agent": agent_name, "events": events}
                )

        except aiohttp.ClientError as e:
            logger.error("Chat proxy: connection to gridbear failed: %s", e)
            return api_error(503, "Cannot reach gridbear service", "connection_error")
