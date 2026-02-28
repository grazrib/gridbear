"""Tests for Claude ToolAdapter."""

from unittest.mock import AsyncMock, MagicMock, patch

from plugins.claude.tool_adapter import ToolAdapter


def _mock_response(data: dict, status: int = 200):
    """Create a mock aiohttp response context manager."""
    mock_resp = AsyncMock()
    mock_resp.status = status
    mock_resp.json = AsyncMock(return_value=data)

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _adapter():
    """Create a ToolAdapter with mocked session."""
    ta = ToolAdapter(gateway_url="http://test-gateway:8080")
    ta._agent_id = "peggy"
    ta._token = "test-token"
    ta._headers = {"Authorization": "Bearer test-token"}
    ta._session = MagicMock()
    ta._session.closed = False
    return ta


class TestToolAdapterRequest:
    """Tests for JSON-RPC request handling."""

    async def test_basic_request(self):
        adapter = _adapter()
        response_data = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": []},
        }
        adapter._session.post = MagicMock(return_value=_mock_response(response_data))

        result = await adapter._request("tools/list", {})
        assert result == response_data
        adapter._session.post.assert_called_once()

    async def test_401_triggers_token_refresh(self):
        adapter = _adapter()
        first_resp = _mock_response({}, status=401)
        retry_resp = _mock_response(
            {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
        )

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return first_resp if call_count == 1 else retry_resp

        adapter._session.post = MagicMock(side_effect=side_effect)

        mock_tm = MagicMock()
        mock_tm.get_token.return_value = "new-token"

        with patch(
            "core.mcp_token_manager.get_mcp_token_manager",
            return_value=mock_tm,
        ):
            result = await adapter._request("tools/list", {})

        assert result["result"]["tools"] == []
        assert adapter._token == "new-token"

    async def test_not_initialized_returns_error(self):
        ta = ToolAdapter()
        ta._session = None
        result = await ta._request("tools/list", {})
        assert "error" in result


class TestToolAdapterListTools:
    """Tests for list_tools()."""

    async def test_returns_tools(self):
        adapter = _adapter()
        tools = [
            {"name": "odoo__search", "description": "Search Odoo"},
            {"name": "github__create_issue", "description": "Create issue"},
        ]
        response_data = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": tools},
        }
        adapter._session.post = MagicMock(return_value=_mock_response(response_data))

        result = await adapter.list_tools()
        assert len(result) == 2
        assert result[0]["name"] == "odoo__search"

    async def test_caches_tools(self):
        adapter = _adapter()
        tools = [{"name": "tool1", "description": "Test"}]
        response_data = {"jsonrpc": "2.0", "id": 1, "result": {"tools": tools}}
        adapter._session.post = MagicMock(return_value=_mock_response(response_data))

        await adapter.list_tools()
        await adapter.list_tools()
        assert adapter._session.post.call_count == 1

    async def test_invalidate_cache(self):
        adapter = _adapter()
        tools = [{"name": "tool1", "description": "Test"}]
        response_data = {"jsonrpc": "2.0", "id": 1, "result": {"tools": tools}}
        adapter._session.post = MagicMock(return_value=_mock_response(response_data))

        await adapter.list_tools()
        adapter.invalidate_cache()
        await adapter.list_tools()
        assert adapter._session.post.call_count == 2

    async def test_error_returns_empty(self):
        adapter = _adapter()
        adapter._session.post = MagicMock(
            return_value=_mock_response({"error": {"message": "fail"}})
        )
        result = await adapter.list_tools()
        assert result == []


class TestToolAdapterCallTool:
    """Tests for call_tool()."""

    async def test_basic_call(self):
        adapter = _adapter()
        response_data = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "content": [{"type": "text", "text": "Search result: 3 records"}]
            },
        }
        adapter._session.post = MagicMock(return_value=_mock_response(response_data))

        result = await adapter.call_tool("odoo__search", {"query": "test"})
        assert len(result) == 1
        assert result[0]["text"] == "Search result: 3 records"

    async def test_error_returns_error_content(self):
        adapter = _adapter()
        adapter._session.post = MagicMock(
            return_value=_mock_response({"error": {"message": "Not found"}})
        )
        result = await adapter.call_tool("unknown_tool", {})
        assert len(result) == 1
        assert "Tool error" in result[0]["text"]


class TestMCPToClaudeTools:
    """Tests for mcp_to_claude_tools()."""

    def test_converts_mcp_tools(self):
        ta = ToolAdapter()
        mcp_tools = [
            {
                "name": "odoo__search_partner",
                "description": "Search for partners in Odoo",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "domain": {"type": "string", "description": "Search filter"},
                        "limit": {"type": "integer", "description": "Max results"},
                    },
                    "required": ["domain"],
                },
            }
        ]
        tools = ta.mcp_to_claude_tools(mcp_tools)
        assert len(tools) == 1
        assert tools[0]["name"] == "odoo__search_partner"
        assert tools[0]["description"] == "Search for partners in Odoo"
        assert tools[0]["input_schema"]["type"] == "object"
        assert "domain" in tools[0]["input_schema"]["properties"]

    def test_tool_without_schema(self):
        ta = ToolAdapter()
        mcp_tools = [{"name": "simple_tool", "description": "No params"}]
        tools = ta.mcp_to_claude_tools(mcp_tools)
        assert len(tools) == 1
        assert tools[0]["input_schema"] == {"type": "object", "properties": {}}

    def test_empty_tools_list(self):
        ta = ToolAdapter()
        assert ta.mcp_to_claude_tools([]) == []

    def test_preserves_json_schema_natively(self):
        """Claude accepts native JSON Schema — no conversion needed."""
        ta = ToolAdapter()
        schema = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "anyOf": [{"type": "string"}, {"type": "integer"}],
                }
            },
        }
        mcp_tools = [{"name": "tool", "description": "Test", "inputSchema": schema}]
        tools = ta.mcp_to_claude_tools(mcp_tools)
        # Schema passed through unchanged (unlike Gemini which needs conversion)
        assert tools[0]["input_schema"] == schema


class TestFormatToolResult:
    """Tests for format_tool_result()."""

    def test_text_content(self):
        ta = ToolAdapter()
        content = [{"type": "text", "text": "Found 3 records"}]
        result = ta.format_tool_result("toolu_123", content)
        assert result["type"] == "tool_result"
        assert result["tool_use_id"] == "toolu_123"
        assert result["content"] == "Found 3 records"
        assert result["is_error"] is False

    def test_multiple_text_parts(self):
        ta = ToolAdapter()
        content = [
            {"type": "text", "text": "Part 1"},
            {"type": "text", "text": "Part 2"},
        ]
        result = ta.format_tool_result("toolu_456", content)
        assert "Part 1" in result["content"]
        assert "Part 2" in result["content"]

    def test_image_content(self):
        ta = ToolAdapter()
        content = [{"type": "image", "data": "base64..."}]
        result = ta.format_tool_result("toolu_789", content)
        assert "[image content]" in result["content"]

    def test_empty_content(self):
        ta = ToolAdapter()
        result = ta.format_tool_result("toolu_000", [])
        assert result["content"] == ""

    def test_error_flag(self):
        ta = ToolAdapter()
        content = [{"type": "text", "text": "Error occurred"}]
        result = ta.format_tool_result("toolu_err", content, is_error=True)
        assert result["is_error"] is True

    def test_tool_use_id_preserved(self):
        """tool_use_id is the correlation key for Claude's tool loop."""
        ta = ToolAdapter()
        content = [{"type": "text", "text": "ok"}]
        result = ta.format_tool_result("toolu_abc123", content)
        assert result["tool_use_id"] == "toolu_abc123"


class TestToolAdapterShutdown:
    """Tests for shutdown()."""

    async def test_closes_session(self):
        ta = ToolAdapter()
        mock_session = AsyncMock()
        mock_session.closed = False
        ta._session = mock_session
        ta._tools_cache = [{"name": "tool"}]

        await ta.shutdown()
        mock_session.close.assert_called_once()
        assert ta._session is None
        assert ta._tools_cache is None

    async def test_shutdown_without_session(self):
        ta = ToolAdapter()
        await ta.shutdown()
