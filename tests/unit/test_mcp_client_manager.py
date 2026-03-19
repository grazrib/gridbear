"""Tests for MCP Gateway client_manager — list_all_tools fallback behavior."""

import json
from unittest.mock import MagicMock, patch

import pytest

from core.mcp_gateway.client_manager import (
    MCPClientManager,
    _mark_token_expired,
    _sanitize_name,
)
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


class TestMarkTokenExpired:
    """Verify that _mark_token_expired sets expires_at=0 in the vault."""

    def test_marks_valid_token_as_expired(self):
        """A valid token JSON should have expires_at set to 0."""
        token_data = {
            "access_token": "abc123",
            "expires_at": 9999999999,
            "refresh_token": "ref456",
        }
        mock_sm = MagicMock()
        mock_sm.get_plain.return_value = json.dumps(token_data)

        with (
            patch(
                "core.mcp_gateway.client_manager.secrets_manager", mock_sm, create=True
            ),
            patch.dict(
                "sys.modules",
                {"ui.secrets_manager": MagicMock(secrets_manager=mock_sm)},
            ),
        ):
            _mark_token_expired("dcorio", "odoo")

        mock_sm.set.assert_called_once()
        call_args = mock_sm.set.call_args
        key = call_args[0][0]
        saved = json.loads(call_args[0][1])

        assert key == "user:dcorio:svc:odoo:token"
        assert saved["expires_at"] == 0
        assert saved["access_token"] == "abc123"
        assert saved["refresh_token"] == "ref456"

    def test_no_token_in_vault_does_nothing(self):
        """If no token exists, _mark_token_expired should be a no-op."""
        mock_sm = MagicMock()
        mock_sm.get_plain.return_value = None

        with (
            patch(
                "core.mcp_gateway.client_manager.secrets_manager", mock_sm, create=True
            ),
            patch.dict(
                "sys.modules",
                {"ui.secrets_manager": MagicMock(secrets_manager=mock_sm)},
            ),
        ):
            _mark_token_expired("nobody", "odoo")

        mock_sm.set.assert_not_called()

    def test_invalid_json_does_nothing(self):
        """If the vault contains invalid JSON, should be a no-op."""
        mock_sm = MagicMock()
        mock_sm.get_plain.return_value = "not-json"

        with (
            patch(
                "core.mcp_gateway.client_manager.secrets_manager", mock_sm, create=True
            ),
            patch.dict(
                "sys.modules",
                {"ui.secrets_manager": MagicMock(secrets_manager=mock_sm)},
            ),
        ):
            _mark_token_expired("dcorio", "odoo")

        mock_sm.set.assert_not_called()
