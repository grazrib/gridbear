"""Home Assistant MCP Provider Plugin.

Provides Home Assistant MCP server configuration (SSE transport).
Camera tools are exposed separately via virtual_tools.py (LocalToolProvider).
"""

import httpx

from config.logging_config import logger
from core.interfaces.mcp_provider import BaseMCPProvider
from ui.secrets_manager import secrets_manager


class HomeAssistantProvider(BaseMCPProvider):
    """Home Assistant MCP server provider."""

    name = "homeassistant"

    # HA SSE endpoint (legacy, session-based) is more reliable with the
    # gateway's asyncio-based timeout handling than the Streamable HTTP
    # endpoint which uses anyio task groups internally.
    _DEFAULT_URL = "http://homeassistant.local:8123/mcp_server/sse"

    def __init__(self, config: dict):
        super().__init__(config)
        self.url = config.get("url", self._DEFAULT_URL)
        token_env = config.get("token_env", "HA_TOKEN")
        self.token = secrets_manager.get_plain(token_env)

    async def initialize(self) -> None:
        """Initialize provider."""
        if not self.token:
            logger.warning("Home Assistant token not configured")
        else:
            logger.info("Home Assistant MCP provider initialized with URL %s", self.url)

    async def shutdown(self) -> None:
        """Cleanup resources."""
        pass

    def get_server_config(self) -> dict:
        """Get MCP server configuration (single SSE server)."""
        if "/api/mcp" in self.url:
            transport = "http"
        else:
            transport = "sse"

        config = {"type": transport, "url": self.url}
        if self.token:
            config["headers"] = {"Authorization": f"Bearer {self.token}"}

        return config

    async def health_check(self) -> bool:
        """Check if MCP server is reachable."""
        if not self.token:
            return False

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                url = self.url
                for suffix in ("/mcp_server/sse", "/api/mcp"):
                    if url.endswith(suffix):
                        url = url[: -len(suffix)]
                        break
                headers = {"Authorization": f"Bearer {self.token}"}
                response = await client.get(f"{url}/api/", headers=headers)
                return response.status_code == 200
        except Exception as e:
            logger.warning("Home Assistant MCP health check failed: %s", e)
            return False
