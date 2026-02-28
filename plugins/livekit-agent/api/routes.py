"""LiveKit Agent Internal API endpoints.

Provides LLM bridge endpoint for the LiveKit worker voice agent.
Previously hardcoded in core/internal_api/server.py.
"""

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel

from config.logging_config import logger
from config.settings import get_unified_user_id
from core.api_schemas import ApiResponse, api_error, api_ok
from core.interfaces.channel import Message, UserInfo
from core.registry import get_agent_manager, get_plugin_manager

router = APIRouter()


class LLMBridgeRequest(BaseModel):
    text: str
    user_id: str = "livekit-user"
    user_name: str = "Voice User"
    room_name: str = ""
    caller_identity: str | None = None


@router.post(
    "/llm-bridge",
    response_model=ApiResponse[dict],
    response_model_exclude_none=True,
)
async def llm_bridge(request: LLMBridgeRequest):
    """Process an LLM request from the LiveKit worker voice agent.

    Simplified version of /chat that returns plain JSON (not streaming)
    for use by the GridBearLLM adapter in the worker subprocess.
    """
    plugin_manager = get_plugin_manager()
    agent_manager = get_agent_manager()

    if not plugin_manager or not agent_manager:
        return api_error(503, "GridBear not initialized", "unavailable")

    if not request.text.strip():
        return api_error(422, "empty text", "validation_error")

    # Find the agent wired to livekit (same logic as main.py wiring)
    target_agent = None
    for agent in agent_manager._agents.values():
        mcp_perms = agent.config.mcp_permissions or []
        if "livekit-agent" in mcp_perms:
            target_agent = agent
            break

    if not target_agent:
        # Fallback to first agent with channels
        for agent in agent_manager._agents.values():
            if agent._channels:
                target_agent = agent
                break

    if not target_agent:
        return api_error(503, "no agent available", "unavailable")

    agent_context = {
        "name": target_agent.name,
        "display_name": target_agent.display_name,
        "system_prompt": target_agent.system_prompt,
        "voice": {
            "provider": target_agent.config.voice.provider,
            "voice_id": target_agent.config.voice.voice_id,
            "language": target_agent.config.voice.language,
        },
        "mcp_permissions": target_agent.config.mcp_permissions,
        "locale": target_agent.config.locale,
        "email": target_agent.email_settings,
    }

    from main import AgentAwareMessageProcessor

    processor = AgentAwareMessageProcessor(plugin_manager, agent_context)

    # Resolve real platform/username/unified_id from caller_identity
    # (format "platform:username", e.g. "telegram:johndoe")
    platform = "livekit"
    username = request.user_name
    unified_id = None
    if request.caller_identity and ":" in request.caller_identity:
        platform, username = request.caller_identity.split(":", 1)
        unified_id = get_unified_user_id(platform, username)
        logger.info(
            "LiveKit bridge resolved identity: %s:%s → %s",
            platform,
            username,
            unified_id,
        )

    message = Message(
        user_id=0,
        username=username,
        text=request.text,
        platform=platform,
        respond_with_voice=True,
    )

    user_info = UserInfo(
        user_id=0,
        username=username,
        display_name=request.user_name,
        platform=platform,
        unified_id=unified_id,
    )

    try:
        result = await asyncio.wait_for(
            processor.process_message(message, user_info),
            timeout=120.0,
        )
        return api_ok(data={"text": result or ""})
    except asyncio.TimeoutError:
        logger.error("LLM bridge request timed out")
        return api_error(408, "timeout", "timeout")
    except Exception as e:
        logger.error(f"LLM bridge error: {e}", exc_info=True)
        return api_error(500, str(e), "internal_error")
