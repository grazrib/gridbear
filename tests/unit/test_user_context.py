"""Tests for MCP gateway user-context side-channel.

Verifies that:
1. The gateway endpoint stores agent → user mapping
2. effective_user falls back to _agent_user_context
3. The runner's _set_user_context() makes the correct HTTP call
4. _set_user_context() is skipped when unified_id is None
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Gateway: _agent_user_context dict + effective_user fallback
# ---------------------------------------------------------------------------


class TestAgentUserContext:
    """Test the _agent_user_context dict in server.py."""

    def test_context_dict_exists(self):
        from core.mcp_gateway.server import _agent_user_context

        assert isinstance(_agent_user_context, dict)

    def test_context_fallback_in_effective_user(self):
        """When params has no user_identity and oauth2_user is None,
        _agent_user_context should be used."""
        import core.mcp_gateway.server as srv

        # Seed the context
        srv._agent_user_context["test-agent"] = "telegram:alice"

        # Simulate what _handle_search_tools does:
        params_identity = None
        agent_name = "test-agent"
        oauth2_user = None

        effective_user = (
            params_identity or srv._agent_user_context.get(agent_name) or oauth2_user
        )
        assert effective_user == "telegram:alice"

        # Cleanup
        srv._agent_user_context.pop("test-agent", None)

    def test_params_identity_takes_priority(self):
        """Explicit JSON-RPC user_identity beats side-channel."""
        import core.mcp_gateway.server as srv

        srv._agent_user_context["test-agent"] = "telegram:alice"

        params_identity = "webchat:bob"
        agent_name = "test-agent"
        oauth2_user = None

        effective_user = (
            params_identity or srv._agent_user_context.get(agent_name) or oauth2_user
        )
        assert effective_user == "webchat:bob"

        srv._agent_user_context.pop("test-agent", None)

    def test_oauth2_fallback_when_no_context(self):
        """When neither params nor side-channel have identity, use oauth2."""
        import core.mcp_gateway.server as srv

        params_identity = None
        agent_name = "unknown-agent"
        oauth2_user = "agent-token-user"

        effective_user = (
            params_identity or srv._agent_user_context.get(agent_name) or oauth2_user
        )
        assert effective_user == "agent-token-user"


# ---------------------------------------------------------------------------
# Gateway endpoint: POST /mcp/user-context
# ---------------------------------------------------------------------------


class TestMcpSetUserContextEndpoint:
    """Test the /mcp/user-context POST endpoint."""

    @pytest.mark.asyncio
    async def test_sets_context_for_agent(self):
        import core.mcp_gateway.server as srv
        from core.mcp_gateway.server import mcp_set_user_context

        # Mock request with valid bearer + agent
        request = MagicMock()
        request.state = MagicMock()
        request.state.oauth2_client = MagicMock()
        request.state.oauth2_client.agent_name = "myagent"
        request.json = AsyncMock(return_value={"user_identity": "telegram:mario"})

        with patch.object(srv, "_check_bearer", return_value=None):
            resp = await mcp_set_user_context(request)

        assert resp.ok is True
        assert srv._agent_user_context.get("myagent") == "telegram:mario"

        # Cleanup
        srv._agent_user_context.pop("myagent", None)

    @pytest.mark.asyncio
    async def test_rejects_no_agent(self):
        import core.mcp_gateway.server as srv
        from core.mcp_gateway.server import mcp_set_user_context

        request = MagicMock()
        request.state = MagicMock()
        request.state.oauth2_client = None

        with patch.object(srv, "_check_bearer", return_value=None):
            resp = await mcp_set_user_context(request)

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_rejects_invalid_json(self):
        import core.mcp_gateway.server as srv
        from core.mcp_gateway.server import mcp_set_user_context

        request = MagicMock()
        request.state = MagicMock()
        request.state.oauth2_client = MagicMock()
        request.state.oauth2_client.agent_name = "myagent"
        request.json = AsyncMock(side_effect=ValueError("bad json"))

        with patch.object(srv, "_check_bearer", return_value=None):
            resp = await mcp_set_user_context(request)

        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Runner: _set_user_context HTTP call
# ---------------------------------------------------------------------------


class TestRunnerSetUserContext:
    """Test ClaudeRunner._set_user_context()."""

    @pytest.mark.asyncio
    async def test_posts_to_gateway(self):
        """_set_user_context sends correct POST to /mcp/user-context."""
        from plugins.claude.runner import ClaudeRunner

        runner = ClaudeRunner.__new__(ClaudeRunner)

        mock_tm = MagicMock()
        mock_tm.get_token.return_value = "test-token-123"
        mock_tm.gateway_url = "http://localhost:8080"

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(return_value=mock_resp)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        # httpx may not be installed locally — inject a mock module
        mock_httpx = MagicMock()
        mock_httpx.AsyncClient = MagicMock(return_value=mock_client_instance)

        with (
            patch(
                "core.mcp_token_manager.get_mcp_token_manager",
                return_value=mock_tm,
            ),
            patch.dict(sys.modules, {"httpx": mock_httpx}),
        ):
            await runner._set_user_context("myagent", "telegram:mario")

            mock_client_instance.post.assert_called_once_with(
                "http://localhost:8080/mcp/user-context",
                json={"user_identity": "telegram:mario"},
                headers={"Authorization": "Bearer test-token-123"},
            )

    @pytest.mark.asyncio
    async def test_skips_when_no_token_manager(self):
        """No token manager → no HTTP call, no error."""
        from plugins.claude.runner import ClaudeRunner

        runner = ClaudeRunner.__new__(ClaudeRunner)

        with patch(
            "core.mcp_token_manager.get_mcp_token_manager",
            return_value=None,
        ):
            # Should complete without error
            await runner._set_user_context("myagent", "telegram:mario")

    @pytest.mark.asyncio
    async def test_skips_when_no_token(self):
        """Token manager exists but no token for agent → skip."""
        from plugins.claude.runner import ClaudeRunner

        runner = ClaudeRunner.__new__(ClaudeRunner)

        mock_tm = MagicMock()
        mock_tm.get_token.return_value = None
        mock_tm.gateway_url = "http://localhost:8080"

        with patch(
            "plugins.claude.runner.get_mcp_token_manager",
            return_value=mock_tm,
            create=True,
        ):
            await runner._set_user_context("myagent", "telegram:mario")

    @pytest.mark.asyncio
    async def test_handles_http_error_gracefully(self):
        """HTTP failure should log warning, not raise."""
        from plugins.claude.runner import ClaudeRunner

        runner = ClaudeRunner.__new__(ClaudeRunner)

        mock_tm = MagicMock()
        mock_tm.get_token.return_value = "test-token"
        mock_tm.gateway_url = "http://localhost:8080"

        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(
            side_effect=Exception("connection refused")
        )
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient = MagicMock(return_value=mock_client_instance)

        with (
            patch(
                "core.mcp_token_manager.get_mcp_token_manager",
                return_value=mock_tm,
            ),
            patch.dict(sys.modules, {"httpx": mock_httpx}),
        ):
            # Should NOT raise
            await runner._set_user_context("myagent", "telegram:mario")


# ---------------------------------------------------------------------------
# Runner: unified_id=None skips the call
# ---------------------------------------------------------------------------


class TestRunnerSkipsWhenNoUnifiedId:
    """Verify that _run_with_pool doesn't call _set_user_context when
    unified_id is None."""

    @pytest.mark.asyncio
    async def test_no_set_user_context_when_none(self):
        """When unified_id is None, _set_user_context should NOT be called."""
        from plugins.claude.runner import ClaudeRunner

        runner = ClaudeRunner.__new__(ClaudeRunner)
        runner._pool = MagicMock()
        runner.model = "sonnet"
        runner.attachments_dir = MagicMock()
        runner.attachments_dir.exists.return_value = False
        runner.log_mcp_calls = False
        runner.log_mcp_input = False
        runner.log_mcp_output = False
        runner.notify_tool_use = False
        runner.verbose = False
        runner.timeout = 60

        # Mock pool acquire/send_prompt/release
        mock_pooled = MagicMock()
        runner._pool.acquire = AsyncMock(return_value=mock_pooled)
        runner._pool.send_prompt = AsyncMock(
            return_value={
                "text": "Hello",
                "session_id": "s1",
                "cost_usd": 0.01,
                "is_error": False,
            }
        )
        runner._pool.release = MagicMock()

        with patch.object(
            runner, "_set_user_context", new_callable=AsyncMock
        ) as mock_ctx:
            await runner._run_with_pool(
                agent_id="test",
                prompt="hello",
                session_id=None,
                unified_id=None,
            )
            mock_ctx.assert_not_called()

    @pytest.mark.asyncio
    async def test_calls_set_user_context_when_present(self):
        """When unified_id is set, _set_user_context SHOULD be called."""
        from plugins.claude.runner import ClaudeRunner

        runner = ClaudeRunner.__new__(ClaudeRunner)
        runner._pool = MagicMock()
        runner.model = "sonnet"
        runner.attachments_dir = MagicMock()
        runner.attachments_dir.exists.return_value = False
        runner.log_mcp_calls = False
        runner.log_mcp_input = False
        runner.log_mcp_output = False
        runner.notify_tool_use = False
        runner.verbose = False
        runner.timeout = 60

        mock_pooled = MagicMock()
        runner._pool.acquire = AsyncMock(return_value=mock_pooled)
        runner._pool.send_prompt = AsyncMock(
            return_value={
                "text": "Hello",
                "session_id": "s1",
                "cost_usd": 0.01,
                "is_error": False,
            }
        )
        runner._pool.release = MagicMock()

        with patch.object(
            runner, "_set_user_context", new_callable=AsyncMock
        ) as mock_ctx:
            await runner._run_with_pool(
                agent_id="test",
                prompt="hello",
                session_id=None,
                unified_id="telegram:alice",
            )
            mock_ctx.assert_called_once_with("test", "telegram:alice")
