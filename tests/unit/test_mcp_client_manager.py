"""Tests for MCP Gateway client_manager — list_all_tools fallback behavior."""

from unittest.mock import patch

import pytest

from core.mcp_gateway.client_manager import MCPClientManager, _sanitize_name
from core.mcp_gateway.provider_loader import ServerInfo


class TestListAllToolsFallback:
    """Verify that user-aware servers fall back to shared connection
    when no unified_id is provided (agent token scenario)."""

    @pytest.fixture
    def manager(self):
        mgr = MCPClientManager()
        mgr._known_servers["homeassistant"] = ServerInfo(
            server_name="homeassistant",
            config={"type": "sse", "url": "http://ha:8123"},
            transport="sse",
            provider_name="homeassistant",
            user_aware=False,
        )
        mgr._known_servers["odoo-mcp"] = ServerInfo(
            server_name="odoo-mcp",
            config={"type": "sse", "url": "https://odoo/mcp/sse"},
            transport="sse",
            provider_name="odoo",
            user_aware=True,
            service_connection_id="odoo",
        )
        # Rebuild sanitized mapping (as refresh_providers does)
        mgr._sanitized_to_original = {}
        for name in mgr._known_servers:
            sanitized = _sanitize_name(name)
            mgr._sanitized_to_original[sanitized] = name
        return mgr

    @pytest.mark.asyncio
    async def test_without_unified_id_skips_user_aware(self, manager):
        """User-aware servers should be skipped when no unified_id is set."""
        ha_tools = [{"name": "turn_on", "description": "Turn on", "inputSchema": {}}]

        async def mock_get_server_tools(server_name):
            if server_name == "homeassistant":
                return ha_tools
            return []

        manager._get_server_tools = mock_get_server_tools

        tools = await manager.list_all_tools(unified_id=None)
        names = {t["name"] for t in tools}
        assert "homeassistant__turn_on" in names
        # user-aware server (odoo-mcp) excluded — no credentials without user
        assert not any("odoo-mcp" in n for n in names)

    @pytest.mark.asyncio
    async def test_without_unified_id_returns_non_user_aware_only(self, manager):
        """Only non-user-aware servers return tools without user context."""

        async def mock_get_server_tools(server_name):
            return [{"name": "tool1", "description": "d", "inputSchema": {}}]

        manager._get_server_tools = mock_get_server_tools

        tools = await manager.list_all_tools(unified_id=None)
        # Only homeassistant (non-user-aware), odoo-mcp skipped
        assert len(tools) == 1

    @pytest.mark.asyncio
    async def test_with_unified_id_uses_user_connection(self, manager):
        """When unified_id is present, user-aware servers use user credentials."""
        user_tools = [{"name": "search", "description": "Search", "inputSchema": {}}]

        async def mock_get_server_tools(server_name):
            return [{"name": "tool1", "description": "d", "inputSchema": {}}]

        async def mock_get_user_server_tools(server_name, uid, creds):
            return user_tools

        manager._get_server_tools = mock_get_server_tools
        manager._get_user_server_tools = mock_get_user_server_tools

        with patch(
            "core.mcp_gateway.client_manager._get_user_credentials",
            return_value={"access_token": "tok123"},
        ):
            tools = await manager.list_all_tools(unified_id="user1")

        names = {t["name"] for t in tools}
        assert "odoo-mcp__search" in names
        assert "homeassistant__tool1" in names
