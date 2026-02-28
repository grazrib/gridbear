"""Tests for Gemini runner (mocked SDK)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.interfaces.runner import RunnerResponse


@pytest.fixture
def mock_genai():
    """Mock google.genai module before importing GeminiRunner."""
    mock_module = MagicMock()
    mock_types = MagicMock()
    mock_module.Client = MagicMock
    with (
        patch.dict(
            "sys.modules",
            {
                "google": MagicMock(),
                "google.genai": mock_module,
                "google.genai.types": mock_types,
            },
        ),
        patch("plugins.gemini.runner.calculate_cost", return_value=0.001),
    ):
        yield mock_module, mock_types


@pytest.fixture
def runner(mock_genai):
    """Create a GeminiRunner with mocked client."""
    from plugins.gemini.runner import GeminiRunner

    r = GeminiRunner({"model": "gemini-2.0-flash", "timeout": 30})

    # Set up mock client
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Hello from Gemini!"
    mock_response.prompt_feedback = None
    mock_response.usage_metadata = MagicMock()
    mock_response.usage_metadata.prompt_token_count = 100
    mock_response.usage_metadata.candidates_token_count = 50
    # No function calls in basic response
    mock_response.candidates = []

    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
    r._client = mock_client

    return r, mock_client, mock_response


class TestGeminiRunnerInit:
    """Tests for runner initialization."""

    def test_default_config(self, mock_genai):
        from plugins.gemini.runner import GeminiRunner

        r = GeminiRunner({})
        assert r.model == "gemini-2.0-flash"
        assert r.timeout == 120
        assert r.temperature == 0.7
        assert r.max_output_tokens == 8192
        assert r.max_tool_iterations == 20

    def test_custom_config(self, mock_genai):
        from plugins.gemini.runner import GeminiRunner

        r = GeminiRunner(
            {
                "model": "gemini-2.5-pro",
                "timeout": 60,
                "temperature": 0.3,
                "max_output_tokens": 4096,
                "max_tool_iterations": 10,
            }
        )
        assert r.model == "gemini-2.5-pro"
        assert r.timeout == 60
        assert r.temperature == 0.3
        assert r.max_output_tokens == 4096
        assert r.max_tool_iterations == 10

    def test_name_attribute(self, mock_genai):
        from plugins.gemini.runner import GeminiRunner

        r = GeminiRunner({})
        assert r.name == "gemini"

    def test_has_session_manager(self, mock_genai):
        from plugins.gemini.runner import GeminiRunner
        from plugins.gemini.session_manager import SessionManager

        r = GeminiRunner({})
        assert isinstance(r._sessions, SessionManager)

    def test_has_tool_adapter(self, mock_genai):
        from plugins.gemini.runner import GeminiRunner
        from plugins.gemini.tool_adapter import ToolAdapter

        r = GeminiRunner({})
        assert isinstance(r._tool_adapter, ToolAdapter)


class TestGeminiRunnerProperties:
    """Tests for runner properties."""

    def test_available_models(self, mock_genai):
        from plugins.gemini.runner import GeminiRunner

        r = GeminiRunner({})
        models = r.available_models
        assert len(models) > 0
        values = [m[0] for m in models]
        assert "gemini-2.0-flash" in values
        assert "gemini-2.5-pro" in values

    async def test_supports_tools(self, mock_genai):
        from plugins.gemini.runner import GeminiRunner

        r = GeminiRunner({})
        assert await r.supports_tools() is True

    async def test_supports_vision(self, mock_genai):
        from plugins.gemini.runner import GeminiRunner

        r = GeminiRunner({})
        assert await r.supports_vision() is True


class TestGeminiRunnerRun:
    """Tests for run() method."""

    async def test_basic_run(self, runner):
        r, mock_client, _ = runner
        result = await r.run(prompt="Hello")

        assert isinstance(result, RunnerResponse)
        assert result.text == "Hello from Gemini!"
        assert result.is_error is False
        assert result.cost_usd == 0.001
        assert result.raw["runner"] == "gemini"
        mock_client.aio.models.generate_content.assert_called_once()

    async def test_returns_session_id(self, runner):
        """Run returns a session_id for multi-turn support."""
        r, _, _ = runner
        result = await r.run(prompt="Hello")
        assert result.session_id is not None
        assert len(result.session_id) > 0

    async def test_session_continuity(self, runner):
        """Passing session_id reuses the same session."""
        r, _, _ = runner
        r1 = await r.run(prompt="Hello")
        r2 = await r.run(prompt="How are you?", session_id=r1.session_id)
        assert r1.session_id == r2.session_id

    async def test_model_override(self, runner):
        r, mock_client, _ = runner
        await r.run(prompt="Test", model="gemini-2.5-pro")

        call_kwargs = mock_client.aio.models.generate_content.call_args
        assert call_kwargs.kwargs["model"] == "gemini-2.5-pro"

    async def test_default_model_used(self, runner):
        r, mock_client, _ = runner
        await r.run(prompt="Test")

        call_kwargs = mock_client.aio.models.generate_content.call_args
        assert call_kwargs.kwargs["model"] == "gemini-2.0-flash"

    async def test_no_tools_skips_tool_setup(self, runner):
        """no_tools=True doesn't attempt tool loading."""
        r, _, _ = runner
        with patch.object(r, "_setup_tools") as mock_setup:
            result = await r.run(prompt="Test", no_tools=True, agent_id="peggy")
            mock_setup.assert_not_called()
        assert result.is_error is False

    async def test_system_prompt_passed_as_system_instruction(self, runner, mock_genai):
        """system_prompt kwarg is used as system_instruction in gen config."""
        r, _, _ = runner
        mock_module, _ = mock_genai

        await r.run(prompt="Hello", system_prompt="Sei Penny, assistente tecnica")

        # types.GenerateContentConfig is mock_module.types.GenerateContentConfig
        config_class = mock_module.types.GenerateContentConfig
        config_class.assert_called()
        last_kwargs = config_class.call_args.kwargs
        assert last_kwargs.get("system_instruction") == "Sei Penny, assistente tecnica"

    async def test_no_system_prompt_omits_system_instruction(self, runner, mock_genai):
        """Without system_prompt, system_instruction is not set."""
        r, _, _ = runner
        mock_module, _ = mock_genai

        await r.run(prompt="Hello")

        config_class = mock_module.types.GenerateContentConfig
        config_class.assert_called()
        last_kwargs = config_class.call_args.kwargs
        assert "system_instruction" not in last_kwargs

    async def test_use_pool_ignored(self, runner):
        r, _, _ = runner
        result = await r.run(prompt="Test", use_pool=True)
        assert result.is_error is False

    async def test_agent_id_passed(self, runner):
        r, _, _ = runner
        result = await r.run(prompt="Test", agent_id="peggy")
        assert result.is_error is False

    async def test_client_not_initialized(self, mock_genai):
        from plugins.gemini.runner import GeminiRunner

        r = GeminiRunner({})
        r._client = None
        result = await r.run(prompt="Test")

        assert result.is_error is True
        assert "not initialized" in result.text

    async def test_client_not_initialized_calls_error_callback(self, mock_genai):
        from plugins.gemini.runner import GeminiRunner

        r = GeminiRunner({})
        r._client = None
        error_cb = AsyncMock()
        await r.run(prompt="Test", error_callback=error_cb)

        error_cb.assert_called_once()

    async def test_api_exception(self, runner):
        r, mock_client, _ = runner
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=Exception("API quota exceeded")
        )
        result = await r.run(prompt="Test")

        assert result.is_error is True
        assert "API quota exceeded" in result.text

    async def test_api_exception_calls_error_callback(self, runner):
        r, mock_client, _ = runner
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=Exception("Network error")
        )
        error_cb = AsyncMock()
        await r.run(prompt="Test", error_callback=error_cb)

        error_cb.assert_called_once()
        assert "Network error" in error_cb.call_args[0][1]

    async def test_safety_block(self, runner):
        r, _, mock_response = runner
        mock_response.prompt_feedback = MagicMock()
        mock_response.prompt_feedback.block_reason = "SAFETY"

        result = await r.run(prompt="Blocked content")

        assert result.is_error is True
        assert "safety filter" in result.text.lower()

    async def test_empty_response_text(self, runner):
        r, _, mock_response = runner
        mock_response.text = ""

        result = await r.run(prompt="Test")

        assert result.is_error is False
        assert result.text == ""

    async def test_none_response_text(self, runner):
        r, _, mock_response = runner
        mock_response.text = None

        result = await r.run(prompt="Test")

        assert result.is_error is False
        assert result.text == ""

    async def test_no_usage_metadata(self, runner):
        r, _, mock_response = runner
        mock_response.usage_metadata = None

        with patch("plugins.gemini.runner.calculate_cost") as mock_cost:
            result = await r.run(prompt="Test")
            mock_cost.assert_not_called()

        assert result.cost_usd == 0.0


class TestGeminiRunnerToolCalls:
    """Tests for the tool call loop."""

    async def test_single_tool_call(self, runner):
        """Tool call → tool result → final text response."""
        r, mock_client, _ = runner

        # First response: function call
        fc_response = MagicMock()
        fc_response.prompt_feedback = None
        fc_response.usage_metadata = MagicMock()
        fc_response.usage_metadata.prompt_token_count = 50
        fc_response.usage_metadata.candidates_token_count = 20
        fc_part = MagicMock()
        fc_part.function_call = MagicMock()
        fc_part.function_call.name = "odoo__search"
        fc_part.function_call.args = {"query": "test"}
        fc_part.text = None
        fc_content = MagicMock()
        fc_content.parts = [fc_part]
        fc_candidate = MagicMock()
        fc_candidate.content = fc_content
        fc_response.candidates = [fc_candidate]

        # Second response: final text
        text_response = MagicMock()
        text_response.text = "Found 3 records"
        text_response.prompt_feedback = None
        text_response.usage_metadata = MagicMock()
        text_response.usage_metadata.prompt_token_count = 80
        text_response.usage_metadata.candidates_token_count = 30
        text_response.candidates = []

        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=[fc_response, text_response]
        )

        # Mock tool adapter
        r._tool_adapter.call_tool = AsyncMock(
            return_value=[{"type": "text", "text": "3 records found"}]
        )
        r._tool_adapter.initialize = AsyncMock()
        r._tool_adapter.list_tools = AsyncMock(
            return_value=[{"name": "odoo__search", "description": "Search"}]
        )

        result = await r.run(prompt="Search Odoo", agent_id="peggy")

        assert result.text == "Found 3 records"
        assert result.is_error is False
        assert result.raw["tool_iterations"] == 1
        r._tool_adapter.call_tool.assert_called_once_with(
            "odoo__search", {"query": "test"}
        )

    async def test_tool_callback_called(self, runner):
        """tool_callback is invoked for each tool call."""
        r, mock_client, _ = runner

        # Function call response
        fc_response = MagicMock()
        fc_response.prompt_feedback = None
        fc_response.usage_metadata = None
        fc_part = MagicMock()
        fc_part.function_call = MagicMock()
        fc_part.function_call.name = "tool1"
        fc_part.function_call.args = {}
        fc_part.text = None
        fc_content = MagicMock()
        fc_content.parts = [fc_part]
        fc_candidate = MagicMock()
        fc_candidate.content = fc_content
        fc_response.candidates = [fc_candidate]

        text_response = MagicMock()
        text_response.text = "Done"
        text_response.prompt_feedback = None
        text_response.usage_metadata = None
        text_response.candidates = []

        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=[fc_response, text_response]
        )

        r._tool_adapter.call_tool = AsyncMock(
            return_value=[{"type": "text", "text": "ok"}]
        )
        r._tool_adapter.initialize = AsyncMock()
        r._tool_adapter.list_tools = AsyncMock(
            return_value=[{"name": "tool1", "description": "T"}]
        )

        tool_cb = AsyncMock()
        await r.run(prompt="Test", agent_id="peggy", tool_callback=tool_cb)

        tool_cb.assert_called_once_with("tool1", {})

    async def test_max_tool_iterations(self, runner):
        """Exceeding max_tool_iterations returns error."""
        r, mock_client, _ = runner
        r.max_tool_iterations = 2

        # Always return function call (infinite loop scenario)
        fc_response = MagicMock()
        fc_response.prompt_feedback = None
        fc_response.usage_metadata = None
        fc_part = MagicMock()
        fc_part.function_call = MagicMock()
        fc_part.function_call.name = "loop_tool"
        fc_part.function_call.args = {}
        fc_part.text = None
        fc_content = MagicMock()
        fc_content.parts = [fc_part]
        fc_candidate = MagicMock()
        fc_candidate.content = fc_content
        fc_response.candidates = [fc_candidate]

        mock_client.aio.models.generate_content = AsyncMock(return_value=fc_response)

        r._tool_adapter.call_tool = AsyncMock(
            return_value=[{"type": "text", "text": "ok"}]
        )
        r._tool_adapter.initialize = AsyncMock()
        r._tool_adapter.list_tools = AsyncMock(
            return_value=[{"name": "loop_tool", "description": "T"}]
        )

        result = await r.run(prompt="Test", agent_id="peggy")

        assert result.is_error is True
        assert "Max tool iterations" in result.text
        assert result.raw["reason"] == "max_tool_iterations"

    async def test_no_agent_id_skips_tools(self, runner):
        """Without agent_id, tools are not loaded."""
        r, _, _ = runner
        with patch.object(r, "_setup_tools") as mock_setup:
            result = await r.run(prompt="Test", agent_id=None)
            mock_setup.assert_not_called()
        assert result.is_error is False


class TestGeminiRunnerExtractFunctionCalls:
    """Tests for _extract_function_calls()."""

    def test_no_candidates(self, mock_genai):
        from plugins.gemini.runner import GeminiRunner

        r = GeminiRunner({})
        mock_resp = MagicMock()
        mock_resp.candidates = []
        assert r._extract_function_calls(mock_resp) == []

    def test_text_only_response(self, mock_genai):
        from plugins.gemini.runner import GeminiRunner

        r = GeminiRunner({})
        mock_resp = MagicMock()
        mock_part = MagicMock()
        mock_part.function_call = None
        mock_part.text = "Hello"
        mock_content = MagicMock()
        mock_content.parts = [mock_part]
        mock_candidate = MagicMock()
        mock_candidate.content = mock_content
        mock_resp.candidates = [mock_candidate]
        assert r._extract_function_calls(mock_resp) == []

    def test_function_call_extracted(self, mock_genai):
        from plugins.gemini.runner import GeminiRunner

        r = GeminiRunner({})
        mock_resp = MagicMock()
        mock_fc = MagicMock()
        mock_fc.name = "search"
        mock_fc.args = {"query": "test"}
        mock_part = MagicMock()
        mock_part.function_call = mock_fc
        mock_content = MagicMock()
        mock_content.parts = [mock_part]
        mock_candidate = MagicMock()
        mock_candidate.content = mock_content
        mock_resp.candidates = [mock_candidate]

        calls = r._extract_function_calls(mock_resp)
        assert len(calls) == 1
        assert calls[0]["name"] == "search"
        assert calls[0]["args"] == {"query": "test"}


class TestGeminiRunnerStreaming:
    """Tests for streaming support."""

    async def test_stream_callback_receives_accumulated_text(self, runner):
        """stream_callback gets full accumulated text, not deltas."""
        r, mock_client, _ = runner

        # Mock streaming response
        chunk1 = MagicMock()
        chunk1.text = "Hello "
        chunk1.candidates = []
        chunk1.prompt_feedback = None
        chunk1.usage_metadata = None

        chunk2 = MagicMock()
        chunk2.text = "world!"
        chunk2.candidates = []
        chunk2.prompt_feedback = None
        chunk2.usage_metadata = MagicMock()
        chunk2.usage_metadata.prompt_token_count = 10
        chunk2.usage_metadata.candidates_token_count = 5

        async def mock_stream(*args, **kwargs):
            for chunk in [chunk1, chunk2]:
                yield chunk

        mock_client.aio.models.generate_content_stream = mock_stream

        stream_cb = AsyncMock()
        result = await r.run(prompt="Test", stream_callback=stream_cb)

        assert result.text == "Hello world!"
        assert result.is_error is False
        # First call: "Hello ", second call: "Hello world!"
        assert stream_cb.call_count == 2
        assert stream_cb.call_args_list[0][0][0] == "Hello "
        assert stream_cb.call_args_list[1][0][0] == "Hello world!"

    async def test_stream_callback_error_does_not_interrupt(self, runner):
        """Errors in stream_callback don't interrupt the stream."""
        r, mock_client, _ = runner

        chunk1 = MagicMock()
        chunk1.text = "Hello"
        chunk1.candidates = []
        chunk1.prompt_feedback = None
        chunk1.usage_metadata = None

        async def mock_stream(*args, **kwargs):
            yield chunk1

        mock_client.aio.models.generate_content_stream = mock_stream

        stream_cb = AsyncMock(side_effect=Exception("callback error"))
        result = await r.run(prompt="Test", stream_callback=stream_cb)

        assert result.text == "Hello"
        assert result.is_error is False

    async def test_no_stream_callback_uses_unary(self, runner):
        """Without stream_callback, uses regular generate_content."""
        r, mock_client, _ = runner
        result = await r.run(prompt="Test", stream_callback=None)

        assert result.is_error is False
        mock_client.aio.models.generate_content.assert_called_once()


class TestGeminiRunnerRetry:
    """Tests for retry with backoff."""

    async def test_retries_on_transient_error(self, runner):
        """Transient error triggers retry."""
        r, mock_client, mock_response = runner
        r.max_retries = 1

        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=[Exception("429 rate limit exceeded"), mock_response]
        )

        with patch("plugins.gemini.runner.asyncio.sleep", new_callable=AsyncMock):
            result = await r.run(prompt="Test")

        assert result.is_error is False
        assert result.text == "Hello from Gemini!"
        assert mock_client.aio.models.generate_content.call_count == 2

    async def test_no_retry_on_non_transient_error(self, runner):
        """Non-transient errors are not retried."""
        r, mock_client, _ = runner
        r.max_retries = 2

        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=Exception("Invalid argument: bad model name")
        )

        result = await r.run(prompt="Test")

        assert result.is_error is True
        assert mock_client.aio.models.generate_content.call_count == 1

    async def test_retry_exhausted(self, runner):
        """After max retries, error is propagated."""
        r, mock_client, _ = runner
        r.max_retries = 2

        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=Exception("503 internal error")
        )

        with patch("plugins.gemini.runner.asyncio.sleep", new_callable=AsyncMock):
            result = await r.run(prompt="Test")

        assert result.is_error is True
        assert "503 internal error" in result.text
        # 1 initial + 2 retries = 3
        assert mock_client.aio.models.generate_content.call_count == 3

    async def test_max_retries_config(self, mock_genai):
        """max_retries is configurable."""
        from plugins.gemini.runner import GeminiRunner

        r = GeminiRunner({"max_retries": 5})
        assert r.max_retries == 5


class TestGeminiRunnerIsTransientError:
    """Tests for _is_transient_error()."""

    def test_rate_limit(self, mock_genai):
        from plugins.gemini.runner import GeminiRunner

        assert GeminiRunner._is_transient_error(Exception("429 rate limit exceeded"))

    def test_quota_exceeded(self, mock_genai):
        from plugins.gemini.runner import GeminiRunner

        assert GeminiRunner._is_transient_error(Exception("Resource exhausted: quota"))

    def test_timeout(self, mock_genai):
        from plugins.gemini.runner import GeminiRunner

        assert GeminiRunner._is_transient_error(Exception("Deadline exceeded"))

    def test_internal_error(self, mock_genai):
        from plugins.gemini.runner import GeminiRunner

        assert GeminiRunner._is_transient_error(Exception("503 internal error"))

    def test_non_transient(self, mock_genai):
        from plugins.gemini.runner import GeminiRunner

        assert not GeminiRunner._is_transient_error(Exception("Invalid argument"))

    def test_permission_denied(self, mock_genai):
        from plugins.gemini.runner import GeminiRunner

        assert not GeminiRunner._is_transient_error(Exception("Permission denied"))


class TestGeminiRunnerSanitizePrompt:
    """Tests for _sanitize_prompt_for_api()."""

    def test_rewrites_mcp_permissions_to_natural_language(self, mock_genai):
        from plugins.gemini.runner import GeminiRunner

        prompt = (
            "Some context\n"
            "[MCP Permissions: For external services, this user can use: "
            "'odoo-mcp', 'gmail-user@example.com', 'homeassistant'. "
            "DO NOT use MCP tools from other servers not listed.]\n"
            "User message"
        )
        result = GeminiRunner._sanitize_prompt_for_api(prompt)
        # Server names removed, natural language used
        assert "'odoo-mcp'" not in result
        assert "MCP Permissions" not in result
        assert "Odoo" in result
        assert "HomeAssistant" in result
        assert "Gmail (user@example.com)" in result
        assert "Available Services" in result
        assert "User message" in result

    def test_rewrites_no_permissions_block(self, mock_genai):
        from plugins.gemini.runner import GeminiRunner

        prompt = (
            "[MCP Permissions: This user has NO access to external MCP tools. "
            "DO NOT use Odoo, Gmail or any other MCP server tools.]"
        )
        result = GeminiRunner._sanitize_prompt_for_api(prompt)
        assert "no access" in result
        assert "MCP Permissions" not in result

    def test_rewrites_ms365_and_gws_servers(self, mock_genai):
        from plugins.gemini.runner import GeminiRunner

        prompt = (
            "[MCP Permissions: For external services, this user can use: "
            "'ms365-Acme', 'gws-user@example.com'. "
            "DO NOT use MCP tools from other servers not listed.]"
        )
        result = GeminiRunner._sanitize_prompt_for_api(prompt)
        assert "Microsoft 365 (Acme)" in result
        assert "Google Workspace (user@example.com)" in result

    def test_rewrites_github_and_playwright(self, mock_genai):
        from plugins.gemini.runner import GeminiRunner

        prompt = (
            "[MCP Permissions: For external services, this user can use: "
            "'github', 'playwright'. "
            "DO NOT use MCP tools from other servers not listed.]"
        )
        result = GeminiRunner._sanitize_prompt_for_api(prompt)
        assert "GitHub" in result
        assert "Web Browser (Playwright)" in result

    def test_removes_builtin_tools_block(self, mock_genai):
        from plugins.gemini.runner import GeminiRunner

        prompt = (
            "[Built-in Tools: You have access to WebSearch and WebFetch "
            "for web searches. Use WebSearch when the user asks for "
            "current news, information, or anything requiring internet search.]"
        )
        result = GeminiRunner._sanitize_prompt_for_api(prompt)
        assert "WebSearch and WebFetch" not in result
        assert "Built-in Tools" not in result

    def test_removes_inline_mcp_tool_references(self, mock_genai):
        from plugins.gemini.runner import GeminiRunner

        prompt = (
            "To operate on a calendar, use "
            "mcp__gmail-user_example_com__list_calendar_events "
            "or mcp__gmail-user_example_com__create_calendar_event."
        )
        result = GeminiRunner._sanitize_prompt_for_api(prompt)
        assert "mcp__gmail" not in result

    def test_removes_mcp_with_clause(self, mock_genai):
        from plugins.gemini.runner import GeminiRunner

        prompt = 'use mcp__gmail-hello__send_email with from_alias="bot" and from_name="Peggy"'
        result = GeminiRunner._sanitize_prompt_for_api(prompt)
        assert "mcp__gmail" not in result
        assert "from_alias" not in result

    def test_replaces_italian_tool_mcp_reference(self, mock_genai):
        """'usa il tool MCP `X`' patterns are replaced."""
        from plugins.gemini.runner import GeminiRunner

        prompt = "Puoi inviare file usando usa il tool MCP `send_file_to_chat`."
        result = GeminiRunner._sanitize_prompt_for_api(prompt)
        assert "tool MCP" not in result
        assert "function call" in result

    def test_collapses_blank_lines(self, mock_genai):
        from plugins.gemini.runner import GeminiRunner

        prompt = "Before\n\n\n\n\nAfter"
        result = GeminiRunner._sanitize_prompt_for_api(prompt)
        assert "\n\n\n" not in result
        assert "Before" in result
        assert "After" in result

    def test_preserves_non_tool_content(self, mock_genai):
        from plugins.gemini.runner import GeminiRunner

        prompt = (
            "Sei Peggy, un'assistente virtuale. Aiuta l'utente con le sue richieste."
        )
        result = GeminiRunner._sanitize_prompt_for_api(prompt)
        assert result == prompt

    def test_handles_empty_prompt(self, mock_genai):
        from plugins.gemini.runner import GeminiRunner

        assert GeminiRunner._sanitize_prompt_for_api("") == ""


class TestGeminiRunnerShutdown:
    """Tests for shutdown."""

    async def test_shutdown_cleans_up(self, mock_genai):
        from plugins.gemini.runner import GeminiRunner

        r = GeminiRunner({})
        r._client = MagicMock()
        r._tool_adapter.shutdown = AsyncMock()
        r._sessions.stop_cleanup_loop = AsyncMock()

        await r.shutdown()

        assert r._client is None
        r._tool_adapter.shutdown.assert_called_once()
        r._sessions.stop_cleanup_loop.assert_called_once()


class TestGeminiRunnerMaxTools:
    """Tests for max_tools config."""

    def test_max_tools_default_unlimited(self, mock_genai):
        from plugins.gemini.runner import GeminiRunner

        r = GeminiRunner({})
        assert r.max_tools == 0

    def test_max_tools_from_config(self, mock_genai):
        from plugins.gemini.runner import GeminiRunner

        r = GeminiRunner({"max_tools": 50})
        assert r.max_tools == 50

    @pytest.mark.asyncio
    async def test_setup_tools_truncates_when_over_limit(self, mock_genai):
        _, mock_types = mock_genai
        from plugins.gemini.runner import GeminiRunner

        r = GeminiRunner({"max_tools": 2})
        r._tool_adapter.initialize = AsyncMock()
        r._tool_adapter.list_tools = AsyncMock(
            return_value=[
                {"name": "t1", "description": "d1", "inputSchema": {}},
                {"name": "t2", "description": "d2", "inputSchema": {}},
                {"name": "t3", "description": "d3", "inputSchema": {}},
            ]
        )
        r._tool_adapter.mcp_to_gemini_declarations = MagicMock(
            return_value=[{"name": "t1"}, {"name": "t2"}]
        )

        await r._setup_tools("test-agent", mock_types)

        # Should have been called with only 2 tools (truncated from 3)
        call_args = r._tool_adapter.mcp_to_gemini_declarations.call_args[0][0]
        assert len(call_args) == 2

    @pytest.mark.asyncio
    async def test_setup_tools_no_truncation_when_under_limit(self, mock_genai):
        _, mock_types = mock_genai
        from plugins.gemini.runner import GeminiRunner

        r = GeminiRunner({"max_tools": 10})
        r._tool_adapter.initialize = AsyncMock()
        r._tool_adapter.list_tools = AsyncMock(
            return_value=[
                {"name": "t1", "description": "d1", "inputSchema": {}},
                {"name": "t2", "description": "d2", "inputSchema": {}},
            ]
        )
        r._tool_adapter.mcp_to_gemini_declarations = MagicMock(
            return_value=[{"name": "t1"}, {"name": "t2"}]
        )

        await r._setup_tools("test-agent", mock_types)

        call_args = r._tool_adapter.mcp_to_gemini_declarations.call_args[0][0]
        assert len(call_args) == 2
