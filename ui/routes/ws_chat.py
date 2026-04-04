"""WebSocket chat handler for user portal.

Provides real-time chat with GridBear agents via WebSocket.
Routes messages through GridBear's internal API for full pipeline processing
(sessions, memory, hooks, context builder, runner, MCP tools).
"""

import asyncio
import json
import os
from pathlib import Path

import aiohttp
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from config.logging_config import logger

router = APIRouter()

GRIDBEAR_URL = os.getenv("GRIDBEAR_INTERNAL_URL", "http://gridbear:8000")
GRIDBEAR_SECRET = os.getenv("INTERNAL_API_SECRET", "")

# Active WebSocket connections: {uid: websocket}
_active_connections: dict[str, WebSocket] = {}

# Background tasks — prevent garbage collection
_background_tasks: set[asyncio.Task] = set()


async def push_to_webchat(uid: str, event: dict) -> bool:
    """Push an event to a user's active WebSocket connection.

    Returns True if delivered, False if user not connected.
    """
    ws = _active_connections.get(uid)
    if not ws:
        logger.debug(f"WebChat push: user {uid} not connected")
        return False
    try:
        await ws.send_json(event)
        return True
    except Exception as exc:
        logger.debug(f"WebChat push failed for {uid}: {exc}")
        _active_connections.pop(uid, None)
        return False


_AGENTS_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "agents"


def _load_agent_yaml(agent_name: str) -> dict | None:
    """Load an agent YAML config by name. Returns None if not found."""
    import yaml

    path = _AGENTS_DIR / f"{agent_name}.yaml"
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return None


async def _authenticate_ws(websocket: WebSocket) -> dict | None:
    """Authenticate WebSocket connection from session cookie."""
    cookies = websocket.cookies
    token = cookies.get("gridbear_session_token")
    if not token:
        return None

    from ui.auth.database import auth_db

    session = auth_db.get_session(token)
    if not session:
        return None

    from datetime import datetime

    from ui.auth.session import _ensure_naive_dt

    if _ensure_naive_dt(session["expires_at"]) < datetime.now():
        return None

    user = auth_db.get_user_by_id(session["user_id"])
    if not user or not user.get("is_active"):
        return None

    return user


async def _stream_from_gridbear(
    text: str,
    user: dict,
    agent_name: str,
    websocket: WebSocket | None,
    conversation_id: str | None = None,
    attachments: list[str] | None = None,
    context_prompt: str | None = None,
) -> str:
    """Send message to GridBear internal API and stream NDJSON events to WebSocket.

    If the WebSocket disconnects mid-stream, processing continues and the
    response is still returned (and saved by the caller).
    """
    uid = user["username"]

    payload = {
        "text": text,
        "user_id": uid,
        "username": user.get("username", ""),
        "display_name": user.get("display_name", ""),
        "agent_name": agent_name,
    }
    if attachments:
        payload["attachments"] = attachments
    if context_prompt:
        payload["context_prompt"] = context_prompt
    if conversation_id:
        payload["channel_metadata"] = {
            "channel": "webchat",
            "conversation_id": conversation_id,
        }
        # Add conversation title
        try:
            from ui.routes.chat_api import get_conversation_title

            title = get_conversation_title(conversation_id)
            if title:
                payload["channel_metadata"]["conversation_title"] = title
        except Exception:
            pass
        if context_prompt:
            payload["channel_metadata"]["conversation_context"] = context_prompt

    ws_alive = True

    async def _try_send(event):
        """Best-effort WebSocket send — silently stops if disconnected."""
        nonlocal ws_alive
        if not ws_alive or not websocket:
            return
        try:
            await websocket.send_json(event)
        except Exception:
            ws_alive = False

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                f"{GRIDBEAR_URL}/api/chat",
                json=payload,
                headers={"Authorization": f"Bearer {GRIDBEAR_SECRET}"},
                timeout=aiohttp.ClientTimeout(total=1800),
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(
                        f"WebChat: GridBear API error {resp.status}: {error_text}"
                    )
                    await _try_send(
                        {
                            "type": "error",
                            "text": f"GridBear API error: {resp.status}",
                        }
                    )
                    return ""

                result_text = ""
                stream_buffer = ""
                async for line in resp.content:
                    line = line.decode().strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # Forward event to browser (best-effort)
                    await _try_send(event)

                    event_type = event.get("type")
                    if event_type == "message":
                        result_text = event.get("text", "")
                    elif event_type == "stream":
                        stream_buffer += event.get("text", "")
                    elif event_type == "stream_end":
                        if stream_buffer and not result_text:
                            result_text = stream_buffer

                return result_text

        except asyncio.TimeoutError:
            logger.error("WebChat: GridBear API timed out")
            await _try_send(
                {
                    "type": "error",
                    "text": "La richiesta ha impiegato troppo tempo.",
                }
            )
            return ""
        except aiohttp.ClientError as e:
            logger.error(f"WebChat: connection to GridBear failed: {e}")
            await _try_send(
                {
                    "type": "error",
                    "text": "Impossibile contattare il servizio GridBear",
                }
            )
            return ""


def _save_message(conversation_id: str | None, role: str, content: str):
    """Persist a message if conversation tracking is active."""
    if not conversation_id or not content:
        return
    try:
        from ui.routes.chat_api import save_message

        save_message(conversation_id, role, content)
    except Exception as e:
        logger.warning(f"WebChat: failed to save message: {e}")


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    """WebSocket endpoint for user chat."""
    user = await _authenticate_ws(websocket)
    if not user:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()

    agent_name = websocket.query_params.get("agent", "")
    conversation_id = websocket.query_params.get("conversation_id", "") or None
    uid = user["username"]

    # Validate agent access: non-superadmins must be in allowed_users
    if agent_name and not user.get("is_superadmin"):
        from ui.routes.me import _get_allowed_users

        agent_cfg = _load_agent_yaml(agent_name)
        if agent_cfg:
            allowed = _get_allowed_users(agent_cfg)
            if not allowed or uid.lower() not in allowed:
                await websocket.send_json(
                    {"type": "error", "text": "Non hai accesso a questo agente"}
                )
                await websocket.close(code=4003, reason="Forbidden")
                return

    # Validate conversation ownership if provided
    if conversation_id:
        from ui.routes.chat_api import validate_conversation_ownership

        if not validate_conversation_ownership(conversation_id, uid):
            await websocket.send_json(
                {"type": "error", "text": "Conversazione non valida"}
            )
            await websocket.close(code=4003, reason="Forbidden")
            return

    logger.info(
        f"WebChat: user {uid} connected to agent {agent_name or 'default'}"
        + (f" conv={conversation_id[:8]}..." if conversation_id else "")
    )

    _active_connections[uid] = websocket

    try:
        while True:
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                break
            except Exception:
                break

            msg_type = data.get("type", "")

            if msg_type == "message":
                text = data.get("text", "").strip()
                attachments = data.get("attachments") or []
                context_prompt = data.get("context_prompt") or None
                if not text and not attachments:
                    continue

                # Persist user message (include attachment info in text if no text)
                save_text = text
                if attachments and not text:
                    save_text = "[allegato]"
                _save_message(conversation_id, "user", save_text)

                # Send typing indicator immediately
                try:
                    await websocket.send_json({"type": "typing"})
                except Exception:
                    pass

                # Run in background so the response is saved even if
                # the user switches conversation (WebSocket disconnects).
                async def _process_message(
                    _text, _user, _agent, _ws, _conv_id, _att, _ctx
                ):
                    try:
                        result = await _stream_from_gridbear(
                            _text,
                            _user,
                            _agent,
                            _ws,
                            _conv_id,
                            attachments=_att,
                            context_prompt=_ctx,
                        )
                        if result:
                            _save_message(_conv_id, "assistant", result)
                            # Notify user of new message (for unread indicator)
                            logger.info(
                                f"WebChat: sending unread for conv={_conv_id[:8]}..."
                            )
                            delivered = await push_to_webchat(
                                _user["username"],
                                {
                                    "type": "unread",
                                    "conversation_id": _conv_id,
                                },
                            )
                            logger.info(
                                f"WebChat: unread delivered={delivered} "
                                f"conv={_conv_id[:8]}..."
                            )

                        if _conv_id:
                            from ui.routes.chat_api import get_conversation_title

                            title = get_conversation_title(_conv_id)
                            if title:
                                try:
                                    await _ws.send_json(
                                        {
                                            "type": "conversation_update",
                                            "conversation_id": _conv_id,
                                            "title": title,
                                        }
                                    )
                                except Exception:
                                    pass
                    except Exception:
                        logger.exception("WebChat: background processing error")

                task = asyncio.create_task(
                    _process_message(
                        text,
                        user,
                        agent_name,
                        websocket,
                        conversation_id,
                        attachments if attachments else None,
                        context_prompt,
                    )
                )
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebChat: connection error: {e}")
    finally:
        _active_connections.pop(uid, None)
        logger.info(f"WebChat: user {uid} disconnected")
