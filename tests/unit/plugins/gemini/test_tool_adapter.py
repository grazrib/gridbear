"""Tests for Gemini ToolAdapter."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from plugins.gemini.tool_adapter import ToolAdapter


@pytest.fixture
def adapter():
    """Create a ToolAdapter with mocked session."""
    ta = ToolAdapter(gateway_url="http://test-gateway:8080")
    ta._agent_id = "peggy"
    ta._token = "test-token"
    ta._headers = {"Authorization": "Bearer test-token"}
    ta._session = MagicMock()
    ta._session.closed = False
    return ta


def _mock_response(data: dict, status: int = 200):
    """Create a mock aiohttp response context manager."""
    mock_resp = AsyncMock()
    mock_resp.status = status
    mock_resp.json = AsyncMock(return_value=data)

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


class TestToolAdapterRequest:
    """Tests for JSON-RPC request handling."""

    async def test_basic_request(self, adapter):
        response_data = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": []},
        }
        adapter._session.post = MagicMock(return_value=_mock_response(response_data))

        result = await adapter._request("tools/list", {})
        assert result == response_data
        adapter._session.post.assert_called_once()

    async def test_incremental_request_ids(self, adapter):
        """Each request gets a unique incremental ID."""
        response_data = {"jsonrpc": "2.0", "id": 1, "result": {}}
        adapter._session.post = MagicMock(return_value=_mock_response(response_data))

        await adapter._request("tools/list", {})
        call1_payload = adapter._session.post.call_args.kwargs["json"]

        await adapter._request("tools/list", {})
        call2_payload = adapter._session.post.call_args.kwargs["json"]

        assert call2_payload["id"] > call1_payload["id"]

    async def test_401_triggers_token_refresh(self, adapter):
        """401 response triggers token refresh and retry."""
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

    async def test_returns_tools(self, adapter):
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

    async def test_caches_tools(self, adapter):
        tools = [{"name": "tool1", "description": "Test"}]
        response_data = {"jsonrpc": "2.0", "id": 1, "result": {"tools": tools}}
        adapter._session.post = MagicMock(return_value=_mock_response(response_data))

        await adapter.list_tools()
        await adapter.list_tools()
        # Only one HTTP call despite two list_tools calls
        assert adapter._session.post.call_count == 1

    async def test_invalidate_cache(self, adapter):
        tools = [{"name": "tool1", "description": "Test"}]
        response_data = {"jsonrpc": "2.0", "id": 1, "result": {"tools": tools}}
        adapter._session.post = MagicMock(return_value=_mock_response(response_data))

        await adapter.list_tools()
        adapter.invalidate_cache()
        await adapter.list_tools()
        assert adapter._session.post.call_count == 2

    async def test_error_returns_empty(self, adapter):
        adapter._session.post = MagicMock(
            return_value=_mock_response({"error": {"message": "fail"}})
        )
        result = await adapter.list_tools()
        assert result == []


class TestToolAdapterCallTool:
    """Tests for call_tool()."""

    async def test_basic_call(self, adapter):
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

    async def test_error_returns_error_content(self, adapter):
        adapter._session.post = MagicMock(
            return_value=_mock_response({"error": {"message": "Not found"}})
        )
        result = await adapter.call_tool("unknown_tool", {})
        assert len(result) == 1
        assert "Tool error" in result[0]["text"]


class TestSchemaConversion:
    """Tests for _convert_json_schema()."""

    def test_simple_string(self):
        ta = ToolAdapter()
        result = ta._convert_json_schema({"type": "string", "description": "A name"})
        assert result["type"] == "STRING"
        assert result["description"] == "A name"

    def test_integer(self):
        ta = ToolAdapter()
        result = ta._convert_json_schema({"type": "integer"})
        assert result["type"] == "INTEGER"

    def test_number(self):
        ta = ToolAdapter()
        result = ta._convert_json_schema({"type": "number"})
        assert result["type"] == "NUMBER"

    def test_boolean(self):
        ta = ToolAdapter()
        result = ta._convert_json_schema({"type": "boolean"})
        assert result["type"] == "BOOLEAN"

    def test_enum(self):
        ta = ToolAdapter()
        result = ta._convert_json_schema(
            {
                "type": "string",
                "enum": ["active", "archived"],
            }
        )
        assert result["type"] == "STRING"
        assert result["enum"] == ["active", "archived"]

    def test_nullable(self):
        ta = ToolAdapter()
        result = ta._convert_json_schema({"type": "string", "nullable": True})
        assert result["nullable"] is True

    def test_object_with_properties(self):
        ta = ToolAdapter()
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name"],
        }
        result = ta._convert_json_schema(schema)
        assert result["type"] == "OBJECT"
        assert "name" in result["properties"]
        # required must be a list at object level, not a bool per-property
        assert result["required"] == ["name"]
        assert "required" not in result["properties"]["name"]
        assert "required" not in result["properties"]["age"]

    def test_array_with_items(self):
        ta = ToolAdapter()
        schema = {
            "type": "array",
            "items": {"type": "string"},
        }
        result = ta._convert_json_schema(schema)
        assert result["type"] == "ARRAY"
        assert result["items"]["type"] == "STRING"

    def test_anyof_fallback(self):
        ta = ToolAdapter()
        schema = {
            "anyOf": [{"type": "string"}, {"type": "integer"}],
            "description": "Flexible field",
        }
        result = ta._convert_json_schema(schema)
        assert result["type"] == "STRING"
        assert "Flexible field" in result["description"]

    def test_oneof_fallback(self):
        ta = ToolAdapter()
        schema = {
            "oneOf": [{"type": "string"}, {"type": "null"}],
        }
        result = ta._convert_json_schema(schema)
        assert result["type"] == "STRING"

    def test_empty_schema(self):
        ta = ToolAdapter()
        assert ta._convert_json_schema({}) == {}
        assert ta._convert_json_schema(None) == {}

    def test_unknown_type_fallback(self):
        ta = ToolAdapter()
        result = ta._convert_json_schema({"type": "custom_type"})
        assert result["type"] == "STRING"

    def test_nested_object(self):
        ta = ToolAdapter()
        schema = {
            "type": "object",
            "properties": {
                "address": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string"},
                        "zip": {"type": "string"},
                    },
                },
            },
        }
        result = ta._convert_json_schema(schema)
        assert result["properties"]["address"]["type"] == "OBJECT"
        assert result["properties"]["address"]["properties"]["city"]["type"] == "STRING"


class TestMCPToGeminiDeclarations:
    """Tests for mcp_to_gemini_declarations()."""

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
        declarations = ta.mcp_to_gemini_declarations(mcp_tools)
        assert len(declarations) == 1
        assert declarations[0]["name"] == "odoo__search_partner"
        assert "parameters" in declarations[0]
        assert declarations[0]["parameters"]["required"] == ["domain"]

    def test_tool_without_schema(self):
        ta = ToolAdapter()
        mcp_tools = [{"name": "simple_tool", "description": "No params"}]
        declarations = ta.mcp_to_gemini_declarations(mcp_tools)
        assert len(declarations) == 1
        assert "parameters" not in declarations[0]

    def test_empty_tools_list(self):
        ta = ToolAdapter()
        assert ta.mcp_to_gemini_declarations([]) == []

    def test_sanitizes_hyphens_in_names(self):
        """Gemini function names only allow [a-zA-Z0-9_], hyphens must be replaced."""
        ta = ToolAdapter()
        mcp_tools = [
            {"name": "odoo-mcp__search_records", "description": "Search Odoo"},
            {"name": "github__list_repos", "description": "List repos"},
        ]
        declarations = ta.mcp_to_gemini_declarations(mcp_tools)
        assert declarations[0]["name"] == "odoo_mcp__search_records"
        assert declarations[1]["name"] == "github__list_repos"
        # Reverse map preserves original names
        assert ta._name_map["odoo_mcp__search_records"] == "odoo-mcp__search_records"
        assert "github__list_repos" not in ta._name_map  # no hyphens, no mapping

    def test_no_map_entry_when_name_unchanged(self):
        """Names without hyphens should NOT appear in the reverse map."""
        ta = ToolAdapter()
        mcp_tools = [{"name": "simple_tool", "description": "No hyphens"}]
        ta.mcp_to_gemini_declarations(mcp_tools)
        assert "simple_tool" not in ta._name_map


class TestCallToolNameRestore:
    """Tests for name restoration in call_tool()."""

    async def test_restores_original_name(self, adapter):
        """call_tool should use the original MCP name with hyphens."""
        adapter._name_map = {"odoo_mcp__search": "odoo-mcp__search"}
        response_data = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": [{"type": "text", "text": "ok"}]},
        }
        adapter._session.post = MagicMock(return_value=_mock_response(response_data))

        await adapter.call_tool("odoo_mcp__search", {"query": "test"})

        # Verify the original name was sent to the gateway
        call_payload = adapter._session.post.call_args.kwargs["json"]
        assert call_payload["params"]["name"] == "odoo-mcp__search"


class TestFormatToolResult:
    """Tests for format_tool_result()."""

    def test_text_content(self):
        ta = ToolAdapter()
        content = [{"type": "text", "text": "Found 3 records"}]
        result = ta.format_tool_result("odoo__search", content)
        assert result["role"] == "function"
        fr = result["parts"][0]["function_response"]
        assert fr["name"] == "odoo__search"
        assert "Found 3 records" in fr["response"]["result"]

    def test_multiple_text_parts(self):
        ta = ToolAdapter()
        content = [
            {"type": "text", "text": "Part 1"},
            {"type": "text", "text": "Part 2"},
        ]
        result = ta.format_tool_result("tool", content)
        fr = result["parts"][0]["function_response"]
        assert "Part 1" in fr["response"]["result"]
        assert "Part 2" in fr["response"]["result"]

    def test_image_content(self):
        ta = ToolAdapter()
        content = [{"type": "image", "data": "base64..."}]
        result = ta.format_tool_result("tool", content)
        fr = result["parts"][0]["function_response"]
        assert "[image content]" in fr["response"]["result"]

    def test_empty_content(self):
        ta = ToolAdapter()
        result = ta.format_tool_result("tool", [])
        fr = result["parts"][0]["function_response"]
        assert fr["response"]["result"] == ""


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
