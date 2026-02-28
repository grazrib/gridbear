"""LiveKit Agent MCP Provider Plugin.

Provides MCP tools for starting and managing voice calls.
"""

import os
from pathlib import Path

from config.logging_config import logger
from core.interfaces.mcp_provider import BaseMCPProvider
from ui.secrets_manager import secrets_manager


class LiveKitProvider(BaseMCPProvider):
    """LiveKit MCP server provider."""

    name = "livekit-agent"

    def __init__(self, config: dict):
        super().__init__(config)
        self.server_path = Path(__file__).parent / "server.py"
        self._service = None

    def set_service(self, service) -> None:
        """Set reference to the LiveKitService."""
        self._service = service

    async def initialize(self) -> None:
        """Initialize provider."""
        api_key = secrets_manager.get_plain("LIVEKIT_API_KEY")
        api_secret = secrets_manager.get_plain("LIVEKIT_API_SECRET")

        if not api_key or not api_secret:
            logger.warning(
                "LIVEKIT_API_KEY/SECRET not configured - livekit-agent MCP tools disabled"
            )
            return

        logger.info("LiveKit MCP provider initialized")

    async def shutdown(self) -> None:
        """Cleanup resources."""
        pass

    async def health_check(self) -> bool:
        """Check if LiveKit is configured."""
        api_key = secrets_manager.get_plain("LIVEKIT_API_KEY")
        api_secret = secrets_manager.get_plain("LIVEKIT_API_SECRET")
        return bool(api_key and api_secret)

    def get_allowed_tools(self) -> list[str]:
        """Tools to allow in Claude CLI (pre-authorized, no user confirmation needed)."""
        return [
            "mcp__livekit-agent__start_voice_call",
            "mcp__livekit-agent__end_voice_call",
            "mcp__livekit-agent__list_active_calls",
            "mcp__livekit-agent__get_call_link",
        ]

    def get_server_config(self) -> dict:
        """Get MCP server configuration."""
        api_key = secrets_manager.get_plain("LIVEKIT_API_KEY")
        api_secret = secrets_manager.get_plain("LIVEKIT_API_SECRET")

        if not api_key or not api_secret:
            return {}

        # Load plugin config from DB
        config = {}
        try:
            from core.plugin_registry.models import PluginRegistryEntry

            entry = PluginRegistryEntry.get_sync(name="livekit-agent")
            if entry:
                config = entry.get("config") or {}
        except Exception:
            pass

        ws_url = config.get("ws_url", "")

        return {
            "livekit-agent": {
                "type": "stdio",
                "command": "python3",
                "args": [str(self.server_path)],
                "env": {
                    "LIVEKIT_API_KEY": api_key,
                    "LIVEKIT_API_SECRET": api_secret,
                    "LIVEKIT_WS_URL": ws_url,
                    "AGENT_NAME": config.get("agent_name", "My Agent"),
                    "STT_LANGUAGE": config.get("stt_language", "it"),
                    "TTS_VOICE": config.get("tts_voice", "nova"),
                    "BASE_URL": config.get("base_url")
                    or os.getenv("GRIDBEAR_BASE_URL", ""),
                    "DATABASE_URL": os.getenv("DATABASE_URL", ""),
                },
            }
        }
