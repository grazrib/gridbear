"""Tests for multi-runner support (Phase 0) and fallback runner (Phase 5).

Verifies AgentConfig.runner/fallback_runner fields, _get_runner_models(),
and fallback runner logic in AgentAwareMessageProcessor.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.agent import AgentConfig
from core.interfaces.runner import RunnerResponse


class TestAgentConfigRunner:
    """Tests for runner field in AgentConfig."""

    def test_from_dict_without_runner(self):
        """AgentConfig without runner field defaults to empty string."""
        data = {
            "id": "test-agent",
            "name": "Test Agent",
            "channels": {},
        }
        config = AgentConfig.from_dict(data)
        assert config.runner == ""

    def test_from_dict_with_runner(self):
        """AgentConfig with runner field is parsed correctly."""
        data = {
            "id": "test-agent",
            "name": "Test Agent",
            "runner": "gemini",
            "channels": {},
        }
        config = AgentConfig.from_dict(data)
        assert config.runner == "gemini"

    def test_from_dict_with_runner_and_model(self):
        """Runner and model are independent fields."""
        data = {
            "id": "test-agent",
            "name": "Test Agent",
            "runner": "gemini",
            "model": "gemini-2.0-flash",
            "channels": {},
        }
        config = AgentConfig.from_dict(data)
        assert config.runner == "gemini"
        assert config.model == "gemini-2.0-flash"

    def test_from_dict_preserves_all_fields(self):
        """Runner field doesn't interfere with other fields."""
        data = {
            "id": "peggy",
            "name": "Peggy",
            "description": "Test agent",
            "personality": "Be helpful",
            "locale": "it",
            "timezone": "Europe/Rome",
            "model": "haiku",
            "runner": "claude",
            "avatar": "peggy.png",
            "channels": {},
            "mcp_permissions": ["odoo-mcp"],
        }
        config = AgentConfig.from_dict(data)
        assert config.name == "peggy"
        assert config.display_name == "Peggy"
        assert config.runner == "claude"
        assert config.model == "haiku"
        assert config.locale == "it"
        assert config.mcp_permissions == ["odoo-mcp"]


class TestAgentConfigFallbackRunner:
    """Tests for fallback_runner field in AgentConfig."""

    def test_from_dict_without_fallback(self):
        """AgentConfig without fallback_runner defaults to empty string."""
        data = {
            "id": "test-agent",
            "name": "Test Agent",
            "channels": {},
        }
        config = AgentConfig.from_dict(data)
        assert config.fallback_runner == ""

    def test_from_dict_with_fallback(self):
        """AgentConfig with fallback_runner is parsed correctly."""
        data = {
            "id": "test-agent",
            "name": "Test Agent",
            "runner": "gemini",
            "fallback_runner": "claude",
            "channels": {},
        }
        config = AgentConfig.from_dict(data)
        assert config.runner == "gemini"
        assert config.fallback_runner == "claude"

    def test_fallback_without_runner(self):
        """Fallback runner can be set even without explicit primary runner."""
        data = {
            "id": "test-agent",
            "name": "Test Agent",
            "fallback_runner": "gemini",
            "channels": {},
        }
        config = AgentConfig.from_dict(data)
        assert config.runner == ""
        assert config.fallback_runner == "gemini"


class TestGetRunnerModels:
    """Tests for _get_runner_models() with multiple runners."""

    @pytest.fixture
    def agents_module(self):
        """Import ui.routes.agents with mocked heavy dependencies."""
        import sys

        # Mock Docker-only dependencies not available locally
        mock_webauthn = MagicMock()
        stubs = {
            "webauthn": mock_webauthn,
            "webauthn.helpers": mock_webauthn.helpers,
            "webauthn.helpers.structs": mock_webauthn.helpers.structs,
            "pyotp": MagicMock(),
            "qrcode": MagicMock(),
            "filelock": MagicMock(),
        }
        saved = {}
        for key, val in stubs.items():
            saved[key] = sys.modules.get(key)
            sys.modules[key] = val

        try:
            import ui.routes.agents

            yield ui.routes.agents
        except (ImportError, RuntimeError) as exc:
            pytest.skip(f"Cannot import ui.routes.agents: {exc}")
        finally:
            for key, orig in saved.items():
                if orig is None:
                    sys.modules.pop(key, None)
                else:
                    sys.modules[key] = orig

    def _make_resolver(self, manifests):
        """Create a mock path resolver returning given manifests."""
        resolver = MagicMock()
        resolver.discover_all.return_value = manifests
        return resolver

    def test_no_runners(self, tmp_path, agents_module):
        """Returns empty dict when no runners are enabled."""
        resolver = self._make_resolver(
            {
                "memory": {"type": "service", "name": "memory"},
            }
        )

        with (
            patch.object(agents_module, "BASE_DIR", tmp_path),
            patch("core.registry.get_path_resolver", return_value=resolver),
            patch("ui.plugin_helpers.get_enabled_plugins", return_value=["memory"]),
        ):
            result = agents_module._get_runner_models()
            assert result == {}

    def test_single_runner(self, tmp_path, agents_module):
        """Returns models for a single runner."""
        resolver = self._make_resolver(
            {
                "claude": {
                    "type": "runner",
                    "name": "claude",
                    "config_schema": {
                        "model": {"enum": ["haiku", "sonnet", "opus"]},
                    },
                },
            }
        )

        with (
            patch.object(agents_module, "BASE_DIR", tmp_path),
            patch("core.registry.get_path_resolver", return_value=resolver),
            patch("ui.plugin_helpers.get_enabled_plugins", return_value=["claude"]),
        ):
            result = agents_module._get_runner_models()
            assert "claude" in result
            assert len(result["claude"]) == 3
            assert ("haiku", "Haiku") in result["claude"]

    def test_multiple_runners(self, tmp_path, agents_module):
        """Returns models for all enabled runners."""
        resolver = self._make_resolver(
            {
                "claude": {
                    "type": "runner",
                    "name": "claude",
                    "config_schema": {
                        "model": {"enum": ["haiku", "sonnet", "opus"]},
                    },
                },
                "gemini": {
                    "type": "runner",
                    "name": "gemini",
                    "config_schema": {
                        "model": {
                            "enum": [
                                "gemini-2.0-flash",
                                "gemini-2.0-flash-lite",
                                "gemini-2.0-pro",
                            ]
                        },
                    },
                },
            }
        )

        with (
            patch.object(agents_module, "BASE_DIR", tmp_path),
            patch("core.registry.get_path_resolver", return_value=resolver),
            patch(
                "ui.plugin_helpers.get_enabled_plugins",
                return_value=["claude", "gemini"],
            ),
        ):
            result = agents_module._get_runner_models()
            assert len(result) == 2
            assert "claude" in result
            assert "gemini" in result
            assert len(result["claude"]) == 3
            assert len(result["gemini"]) == 3
            assert ("gemini-2.0-flash", "Gemini-2.0-flash") in result["gemini"]

    def test_runner_without_model_enum(self, tmp_path, agents_module):
        """Runner with no model enum returns empty list."""
        resolver = self._make_resolver(
            {
                "custom": {
                    "type": "runner",
                    "name": "custom",
                    "config_schema": {},
                },
            }
        )

        with (
            patch.object(agents_module, "BASE_DIR", tmp_path),
            patch("core.registry.get_path_resolver", return_value=resolver),
            patch("ui.plugin_helpers.get_enabled_plugins", return_value=["custom"]),
        ):
            result = agents_module._get_runner_models()
            assert "custom" in result
            assert result["custom"] == []


class TestFallbackRunnerLogic:
    """Tests for fallback runner logic in AgentAwareMessageProcessor.

    Tests the core behavior: if primary runner returns is_error=True and
    a fallback_runner is configured, retry with the fallback.
    """

    @pytest.fixture
    def primary_runner(self):
        runner = AsyncMock()
        runner.name = "gemini"
        return runner

    @pytest.fixture
    def fallback_runner(self):
        runner = AsyncMock()
        runner.name = "claude"
        return runner

    @pytest.fixture
    def plugin_manager(self, primary_runner, fallback_runner):
        pm = MagicMock()
        pm.get_service.return_value = None  # No sessions/memory
        pm.get_all_context_injections = AsyncMock(return_value={})

        def _get_runner(name=None):
            if name == "gemini":
                return primary_runner
            if name == "claude":
                return fallback_runner
            return primary_runner  # Default

        pm.get_runner.side_effect = _get_runner
        pm.hooks = MagicMock()
        pm.hooks.execute = AsyncMock(side_effect=lambda event, data, **kw: data)
        return pm

    @pytest.fixture
    def agent_context(self):
        return {
            "name": "test-agent",
            "display_name": "Test Agent",
            "system_prompt": "Be helpful",
            "runner": "gemini",
            "fallback_runner": "claude",
            "model": "",
            "mcp_permissions": [],
            "locale": "en",
        }

    @pytest.mark.asyncio
    async def test_fallback_triggered_on_primary_error(
        self, primary_runner, fallback_runner, plugin_manager, agent_context
    ):
        """When primary runner returns is_error, fallback runner is called."""
        primary_runner.run.return_value = RunnerResponse(
            text="API error", is_error=True
        )
        fallback_runner.run.return_value = RunnerResponse(
            text="Fallback response", is_error=False
        )

        from main import AgentAwareMessageProcessor

        proc = AgentAwareMessageProcessor(plugin_manager, agent_context)
        proc.hooks = plugin_manager.hooks

        from core.interfaces.channel import Message, UserInfo

        msg = Message(user_id=1, username="test", text="Hello", platform="test")
        user = UserInfo(
            user_id=1,
            username="test",
            display_name="Test",
            platform="test",
        )

        with (
            patch("main.get_unified_user_id", return_value=None),
            patch("main.get_group_shared_accounts", return_value={}),
            patch("main.get_user_locale", return_value=None),
            patch("main.resolve_permissions", return_value=[]),
            patch("main.build_inter_agent_context", return_value=""),
            patch("core.registry.get_agent_manager", return_value=None),
        ):
            result = await proc.process_message(msg, user)

        assert result == "Fallback response"
        primary_runner.run.assert_called_once()
        fallback_runner.run.assert_called_once()
        # Fallback should use session_id=None (different runner)
        assert fallback_runner.run.call_args.kwargs.get("session_id") is None

    @pytest.mark.asyncio
    async def test_no_fallback_on_success(
        self, primary_runner, fallback_runner, plugin_manager, agent_context
    ):
        """When primary runner succeeds, fallback is not called."""
        primary_runner.run.return_value = RunnerResponse(text="Success", is_error=False)

        from main import AgentAwareMessageProcessor

        proc = AgentAwareMessageProcessor(plugin_manager, agent_context)
        proc.hooks = plugin_manager.hooks

        from core.interfaces.channel import Message, UserInfo

        msg = Message(user_id=1, username="test", text="Hello", platform="test")
        user = UserInfo(
            user_id=1,
            username="test",
            display_name="Test",
            platform="test",
        )

        with (
            patch("main.get_unified_user_id", return_value=None),
            patch("main.get_group_shared_accounts", return_value={}),
            patch("main.get_user_locale", return_value=None),
            patch("main.resolve_permissions", return_value=[]),
            patch("main.build_inter_agent_context", return_value=""),
            patch("core.registry.get_agent_manager", return_value=None),
        ):
            result = await proc.process_message(msg, user)

        assert result == "Success"
        primary_runner.run.assert_called_once()
        fallback_runner.run.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_fallback_when_not_configured(
        self, primary_runner, plugin_manager, agent_context
    ):
        """When no fallback_runner is set, error response is returned as-is."""
        agent_context["fallback_runner"] = ""
        primary_runner.run.return_value = RunnerResponse(
            text="API error", is_error=True
        )

        from main import AgentAwareMessageProcessor

        proc = AgentAwareMessageProcessor(plugin_manager, agent_context)
        proc.hooks = plugin_manager.hooks

        from core.interfaces.channel import Message, UserInfo

        msg = Message(user_id=1, username="test", text="Hello", platform="test")
        user = UserInfo(
            user_id=1,
            username="test",
            display_name="Test",
            platform="test",
        )

        with (
            patch("main.get_unified_user_id", return_value=None),
            patch("main.get_group_shared_accounts", return_value={}),
            patch("main.get_user_locale", return_value=None),
            patch("main.resolve_permissions", return_value=[]),
            patch("main.build_inter_agent_context", return_value=""),
            patch("core.registry.get_agent_manager", return_value=None),
        ):
            result = await proc.process_message(msg, user)

        assert result == "API error"

    @pytest.mark.asyncio
    async def test_fallback_same_runner_skipped(
        self, primary_runner, plugin_manager, agent_context
    ):
        """When fallback_runner resolves to same runner, skip fallback."""
        agent_context["fallback_runner"] = "gemini"  # Same as primary
        primary_runner.run.return_value = RunnerResponse(
            text="API error", is_error=True
        )

        from main import AgentAwareMessageProcessor

        proc = AgentAwareMessageProcessor(plugin_manager, agent_context)
        proc.hooks = plugin_manager.hooks

        from core.interfaces.channel import Message, UserInfo

        msg = Message(user_id=1, username="test", text="Hello", platform="test")
        user = UserInfo(
            user_id=1,
            username="test",
            display_name="Test",
            platform="test",
        )

        with (
            patch("main.get_unified_user_id", return_value=None),
            patch("main.get_group_shared_accounts", return_value={}),
            patch("main.get_user_locale", return_value=None),
            patch("main.resolve_permissions", return_value=[]),
            patch("main.build_inter_agent_context", return_value=""),
            patch("core.registry.get_agent_manager", return_value=None),
        ):
            result = await proc.process_message(msg, user)

        assert result == "API error"
        # Runner should only be called once (no fallback to itself)
        primary_runner.run.assert_called_once()
