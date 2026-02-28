"""Tests for tool management: budget, metrics, config, search, discovery."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.agent import AgentConfig
from core.mcp_gateway.server import _BUILTIN_PREFIXES, _apply_tool_budget

# --- Helpers ---


def _tool(name):
    """Create a minimal tool dict."""
    return {"name": name, "description": f"Tool {name}"}


def _builtin_tools():
    """Standard set of built-in tools."""
    return [
        _tool("gridbear_help"),
        _tool("send_file_to_chat"),
        _tool("ask_agent"),
        _tool("async_run_tool"),
        _tool("async_task_status"),
        _tool("async_list_tasks"),
        _tool("chat_history__list"),
        _tool("credential_vault__get"),
    ]


def _mcp_tools(server, count):
    """Generate MCP tools for a given server prefix."""
    return [_tool(f"{server}__tool_{i}") for i in range(count)]


# --- _apply_tool_budget tests ---


class TestApplyToolBudget:
    def test_builtin_always_included(self):
        """Built-in tools are never removed by budget."""
        builtins = _builtin_tools()
        mcp = _mcp_tools("odoo_mcp", 20)
        all_tools = builtins + mcp

        result = _apply_tool_budget(all_tools, budget=5)

        # All 8 built-in tools present
        result_names = {t["name"] for t in result}
        for bt in builtins:
            assert bt["name"] in result_names
        # Exactly 5 MCP tools
        mcp_in_result = [
            t for t in result if not t["name"].startswith(_BUILTIN_PREFIXES)
        ]
        assert len(mcp_in_result) == 5

    def test_builtin_outside_budget(self):
        """Budget counts only MCP tools, built-ins are free."""
        builtins = _builtin_tools()
        mcp = _mcp_tools("gmail", 3)
        all_tools = builtins + mcp

        result = _apply_tool_budget(all_tools, budget=10)

        # All tools returned (3 MCP < budget 10)
        assert len(result) == len(builtins) + 3

    def test_round_robin_fair(self):
        """With 3 servers and budget=6, each server gets 2 tools."""
        builtins = _builtin_tools()
        server_a = _mcp_tools("server_a", 10)
        server_b = _mcp_tools("server_b", 10)
        server_c = _mcp_tools("server_c", 10)
        all_tools = builtins + server_a + server_b + server_c

        result = _apply_tool_budget(all_tools, budget=6)

        mcp_result = [t for t in result if not t["name"].startswith(_BUILTIN_PREFIXES)]
        assert len(mcp_result) == 6

        # Count per server
        counts = {}
        for t in mcp_result:
            prefix = t["name"].split("__")[0]
            counts[prefix] = counts.get(prefix, 0) + 1

        assert counts.get("server_a", 0) == 2
        assert counts.get("server_b", 0) == 2
        assert counts.get("server_c", 0) == 2

    def test_zero_budget(self):
        """Budget=0 returns only built-in tools."""
        builtins = _builtin_tools()
        mcp = _mcp_tools("odoo_mcp", 10)
        all_tools = builtins + mcp

        result = _apply_tool_budget(all_tools, budget=0)

        assert len(result) == len(builtins)
        for t in result:
            assert t["name"].startswith(_BUILTIN_PREFIXES)

    def test_budget_larger_than_tools(self):
        """When budget exceeds MCP tool count, all tools returned."""
        builtins = _builtin_tools()
        mcp = _mcp_tools("gmail", 5)
        all_tools = builtins + mcp

        result = _apply_tool_budget(all_tools, budget=100)

        assert len(result) == len(all_tools)

    def test_uneven_servers(self):
        """Round-robin handles servers with different tool counts."""
        builtins = _builtin_tools()
        big = _mcp_tools("big_server", 20)
        small = _mcp_tools("small_server", 2)
        all_tools = builtins + big + small

        result = _apply_tool_budget(all_tools, budget=6)

        mcp_result = [t for t in result if not t["name"].startswith(_BUILTIN_PREFIXES)]
        assert len(mcp_result) == 6

        counts = {}
        for t in mcp_result:
            prefix = t["name"].split("__")[0]
            counts[prefix] = counts.get(prefix, 0) + 1

        # small_server has only 2, rest from big_server
        assert counts["small_server"] == 2
        assert counts["big_server"] == 4


# --- AgentConfig.max_tools tests ---


class TestAgentConfigMaxTools:
    def test_max_tools_from_yaml(self):
        """max_tools parsed from agent YAML config."""
        config = AgentConfig.from_dict({"id": "test", "name": "Test", "max_tools": 25})
        assert config.max_tools == 25

    def test_max_tools_default_none(self):
        """max_tools defaults to None when not specified."""
        config = AgentConfig.from_dict({"id": "test", "name": "Test"})
        assert config.max_tools is None

    def test_max_tools_zero(self):
        """max_tools=0 is preserved (means no MCP tools)."""
        config = AgentConfig.from_dict({"id": "test", "name": "Test", "max_tools": 0})
        assert config.max_tools == 0


# --- _record_tool_usage tests ---


class TestRecordToolUsage:
    @pytest.mark.asyncio
    async def test_records_successful_call(self):
        """Successful tool call is recorded with duration."""
        mock_db = AsyncMock()
        with patch("core.registry.get_database", return_value=mock_db):
            from core.mcp_gateway.server import _record_tool_usage

            await _record_tool_usage("peggy", "odoo_mcp__search_read", True, 150)

        mock_db.execute.assert_called_once()
        args = mock_db.execute.call_args
        assert "INSERT INTO public.tool_usage" in args[0][0]
        assert args[0][1] == ("peggy", "odoo_mcp__search_read", True, 150)

    @pytest.mark.asyncio
    async def test_records_failed_call(self):
        """Failed tool call is recorded with success=False."""
        mock_db = AsyncMock()
        with patch("core.registry.get_database", return_value=mock_db):
            from core.mcp_gateway.server import _record_tool_usage

            await _record_tool_usage("peggy", "gmail__send", False, 3000)

        args = mock_db.execute.call_args
        assert args[0][1] == ("peggy", "gmail__send", False, 3000)

    @pytest.mark.asyncio
    async def test_skips_when_no_agent(self):
        """No recording when agent_name is None."""
        mock_db = AsyncMock()
        with patch("core.registry.get_database", return_value=mock_db):
            from core.mcp_gateway.server import _record_tool_usage

            await _record_tool_usage(None, "some_tool", True, 100)

        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_db_error_silenced(self):
        """DB errors don't propagate — fire-and-forget."""
        mock_db = AsyncMock()
        mock_db.execute.side_effect = RuntimeError("DB down")
        with patch("core.registry.get_database", return_value=mock_db):
            from core.mcp_gateway.server import _record_tool_usage

            # Should not raise
            await _record_tool_usage("peggy", "tool", True, 50)


# --- Phase 2: search_tools + execute_discovered_tool ---


def _tool_with_desc(name, description):
    """Create a tool dict with custom description."""
    return {
        "name": name,
        "description": description,
        "inputSchema": {"type": "object", "properties": {}},
    }


class TestSearchTools:
    @pytest.mark.asyncio
    async def test_keyword_matching(self):
        """search_tools finds tools matching query keywords in name/description."""
        from core.mcp_gateway.server import (
            _discovered_tools,
            _handle_search_tools,
        )

        tools = [
            _tool_with_desc("odoo_mcp__search_invoice", "Search invoices in Odoo"),
            _tool_with_desc("odoo_mcp__create_partner", "Create a partner record"),
            _tool_with_desc("gmail__send_email", "Send an email message"),
        ]

        mock_cm = MagicMock()
        mock_cm.list_all_tools = AsyncMock(return_value=tools)
        mock_cm._sanitized_to_original = {}

        with patch("core.mcp_gateway.server._client_manager", mock_cm):
            result = await _handle_search_tools(
                {"query": "invoice"},
                agent_name="test",
                session_id="sess-1",
            )

        assert len(result) == 1
        text = result[0]["text"]
        assert "search_invoice" in text
        assert "send_email" not in text

        # Cleanup
        _discovered_tools.pop("sess-1", None)

    @pytest.mark.asyncio
    async def test_name_bonus_scoring(self):
        """Match in tool name scores higher than match only in description."""
        from core.mcp_gateway.server import (
            _discovered_tools,
            _handle_search_tools,
        )

        tools = [
            _tool_with_desc("odoo_mcp__list_partners", "List all partner records"),
            _tool_with_desc(
                "gmail__send_email",
                "Send email to partners or contacts",
            ),
        ]

        mock_cm = MagicMock()
        mock_cm.list_all_tools = AsyncMock(return_value=tools)
        mock_cm._sanitized_to_original = {}

        with patch("core.mcp_gateway.server._client_manager", mock_cm):
            result = await _handle_search_tools(
                {"query": "partners"},
                agent_name="test",
                session_id="sess-2",
            )

        import json

        results_list = json.loads(result[0]["text"])
        # list_partners has "partners" in name (3 pts) + desc (1 pt) = 4
        # send_email has "partners" only in desc (1 pt)
        assert results_list[0]["name"] == "odoo_mcp__list_partners"
        assert results_list[1]["name"] == "gmail__send_email"

        _discovered_tools.pop("sess-2", None)

    @pytest.mark.asyncio
    async def test_category_filter(self):
        """category filter limits results to matching server category."""
        from core.mcp_gateway.server import (
            _discovered_tools,
            _handle_search_tools,
            _server_categories,
        )

        tools = [
            _tool_with_desc("odoo_mcp__search_read", "Search Odoo records"),
            _tool_with_desc("gmail__search_email", "Search emails"),
        ]

        mock_cm = MagicMock()
        mock_cm.list_all_tools = AsyncMock(return_value=tools)
        mock_cm._sanitized_to_original = {}

        # Set up category mapping
        _server_categories["odoo_mcp"] = "erp"
        _server_categories["gmail"] = "communication"

        with patch("core.mcp_gateway.server._client_manager", mock_cm):
            result = await _handle_search_tools(
                {"query": "search", "category": "erp"},
                agent_name="test",
                session_id="sess-3",
            )

        import json

        results_list = json.loads(result[0]["text"])
        assert len(results_list) == 1
        assert results_list[0]["name"] == "odoo_mcp__search_read"

        # Cleanup
        _discovered_tools.pop("sess-3", None)
        _server_categories.pop("odoo_mcp", None)
        _server_categories.pop("gmail", None)

    @pytest.mark.asyncio
    async def test_respects_permissions(self):
        """Tools outside MCP permissions are not returned."""
        from core.mcp_gateway.server import (
            _discovered_tools,
            _handle_search_tools,
        )

        tools = [
            _tool_with_desc("odoo_mcp__search_read", "Search Odoo records"),
            _tool_with_desc("gmail__send_email", "Send email"),
        ]

        mock_cm = MagicMock()
        mock_cm.list_all_tools = AsyncMock(return_value=tools)
        mock_cm._sanitized_to_original = {}

        # Only allow gmail
        with (
            patch("core.mcp_gateway.server._client_manager", mock_cm),
            patch(
                "core.mcp_gateway.server._filter_by_permissions",
                side_effect=lambda t, p: [
                    x for x in t if x["name"].startswith("gmail")
                ],
            ),
        ):
            result = await _handle_search_tools(
                {"query": "search"},
                agent_name="test",
                session_id="sess-4",
                mcp_permissions=["gmail"],
            )

        # Only gmail tool should appear (even though odoo also matches "search")
        text = result[0]["text"]
        assert "odoo_mcp" not in text

        _discovered_tools.pop("sess-4", None)


class TestExecuteDiscoveredTool:
    @pytest.mark.asyncio
    async def test_validates_search_required(self):
        """Calling execute_discovered_tool without prior search returns error."""
        from core.mcp_gateway.server import (
            _discovered_tools,
            _handle_execute_discovered,
        )

        # No prior search for this session
        _discovered_tools.pop("sess-new", None)

        result = await _handle_execute_discovered(
            {"tool_name": "odoo_mcp__search_read", "arguments": {}},
            agent_name="test",
            session_id="sess-new",
            oauth2_user=None,
        )

        assert len(result) == 1
        assert "search_tools first" in result[0]["text"]

    @pytest.mark.asyncio
    async def test_executes_after_search(self):
        """After search, execute_discovered_tool delegates to dispatch."""
        from core.mcp_gateway.server import (
            _discovered_tools,
            _handle_execute_discovered,
        )

        # Simulate prior search discovered this tool
        _discovered_tools["sess-ok"] = {"odoo_mcp__search_read"}

        mock_dispatch = AsyncMock(
            return_value=[{"type": "text", "text": "result data"}]
        )

        with (
            patch("core.mcp_gateway.server._dispatch_tool_call", mock_dispatch),
            patch("core.mcp_gateway.server._record_tool_usage", AsyncMock()),
        ):
            result = await _handle_execute_discovered(
                {
                    "tool_name": "odoo_mcp__search_read",
                    "arguments": {"model": "res.partner"},
                },
                agent_name="test",
                session_id="sess-ok",
                oauth2_user="user1",
                mcp_permissions=["odoo-mcp"],
            )

        assert result == [{"type": "text", "text": "result data"}]
        mock_dispatch.assert_called_once_with(
            "odoo_mcp__search_read",
            {"model": "res.partner"},
            "test",
            "user1",
            mcp_permissions=["odoo-mcp"],
        )

        _discovered_tools.pop("sess-ok", None)


class TestSearchModeMinimalTools:
    """test_search_mode_returns_minimal_tools: tool_loading=search returns only built-in."""

    def test_search_tools_in_builtin_prefixes(self):
        """search_tools and execute_discovered_tool are in _BUILTIN_PREFIXES."""
        assert any(p == "search_tools" for p in _BUILTIN_PREFIXES)
        assert any(p == "execute_discovered_tool" for p in _BUILTIN_PREFIXES)


class TestGetServerCategory:
    def test_known_server(self):
        """Known server returns its category."""
        from core.mcp_gateway.server import (
            _get_server_category,
            _server_categories,
        )

        _server_categories["odoo_mcp"] = "erp"
        assert _get_server_category("odoo_mcp") == "erp"
        _server_categories.pop("odoo_mcp", None)

    def test_unknown_server_defaults_system(self):
        """Unknown server defaults to 'system'."""
        from core.mcp_gateway.server import _get_server_category

        assert _get_server_category("unknown_server") == "system"


class TestAgentConfigToolLoading:
    def test_tool_loading_from_yaml(self):
        """tool_loading parsed from agent YAML config."""
        config = AgentConfig.from_dict(
            {"id": "test", "name": "Test", "tool_loading": "search"}
        )
        assert config.tool_loading == "search"

    def test_tool_loading_default_full(self):
        """tool_loading defaults to 'full' when not specified."""
        config = AgentConfig.from_dict({"id": "test", "name": "Test"})
        assert config.tool_loading == "full"


class TestServerInfoCategory:
    def test_server_info_has_category(self):
        """ServerInfo includes category field."""
        from core.mcp_gateway.provider_loader import ServerInfo

        info = ServerInfo(
            server_name="test",
            config={},
            transport="stdio",
            provider_name="test",
            category="erp",
        )
        assert info.category == "erp"

    def test_server_info_default_category(self):
        """ServerInfo defaults category to 'system'."""
        from core.mcp_gateway.provider_loader import ServerInfo

        info = ServerInfo(
            server_name="test",
            config={},
            transport="stdio",
            provider_name="test",
        )
        assert info.category == "system"
