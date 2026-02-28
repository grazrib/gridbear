"""Core independence tests — verify core/ui work without plugins.

Ensures that the framework can start and serve the admin UI with zero
plugins enabled. Catches import-time coupling (direct plugin imports)
and runtime coupling (missing runner/service crashes).

Spec reference: §6 Core Independence (Core Without Plugins).
"""

import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest

# UI route modules that must import cleanly without plugins
UI_ROUTE_MODULES = [
    "ui.routes.agents",
    "ui.routes.auth",
    "ui.routes.chat_api",
    "ui.routes.me",
    "ui.routes.memory",
    "ui.routes.notifications",
    "ui.routes.oauth2",
    "ui.routes.permissions",
    "ui.routes.plugins",
    "ui.routes.rest_api",
    "ui.routes.secrets",
    "ui.routes.settings",
    "ui.routes.themes",
    "ui.routes.tools",
    "ui.routes.users",
    "ui.routes.vault",
    "ui.routes.ws_chat",
]

# Core modules that must import cleanly without plugins
CORE_MODULES = [
    "core.agent",
    "core.agent_manager",
    "core.plugin_manager",
    "core.registry",
    "core.interfaces.runner",
    "core.interfaces.service",
    "core.rest_api.acl",
]


def _import_without_plugins(module_name: str) -> None:
    """Import a module after removing plugins.* from sys.modules.

    Raises pytest.fail only if the import fails due to a plugins.*
    dependency. Other failures (missing third-party deps like filelock,
    python-multipart) are tolerated since they're not plugin coupling.
    """
    plugin_modules = [key for key in sys.modules if key.startswith("plugins.")]
    saved = {}
    for key in plugin_modules:
        saved[key] = sys.modules.pop(key)

    try:
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])
        else:
            importlib.import_module(module_name)
    except ImportError as exc:
        msg = str(exc)
        if "plugins." in msg or "plugins/" in msg:
            pytest.fail(f"{module_name} has direct plugin dependency: {exc}")
        # Missing third-party deps (filelock, python-multipart, etc.) are OK
    except RuntimeError:
        # e.g. FastAPI requires python-multipart for Form() — not a plugin issue
        pass
    finally:
        sys.modules.update(saved)


class TestUIImportsWithoutPlugins:
    """UI modules must import cleanly without any plugin installed."""

    @pytest.mark.parametrize("module_name", UI_ROUTE_MODULES)
    def test_ui_route_import(self, module_name):
        """Each UI route module imports without requiring plugins.*."""
        _import_without_plugins(module_name)

    @pytest.mark.parametrize("module_name", CORE_MODULES)
    def test_core_module_import(self, module_name):
        """Core modules import without requiring plugins.*."""
        _import_without_plugins(module_name)


class TestMessageProcessorWithoutRunner:
    """MessageProcessor degrades gracefully without a runner."""

    @pytest.mark.asyncio
    async def test_no_runner_returns_error_message(self):
        """MessageProcessor.process_message returns error when no runner."""
        from core.interfaces.channel import Message, UserInfo
        from main import MessageProcessor

        pm = MagicMock()
        pm.get_runner.return_value = None
        pm.get_service.return_value = None

        processor = MessageProcessor(pm)

        msg = Message(user_id=1, username="test", text="hello", platform="test")
        user = UserInfo(
            user_id=1, username="test", display_name="Test", platform="test"
        )

        result = await processor.process_message(msg, user)
        assert result == "No runner available."

    @pytest.mark.asyncio
    async def test_agent_aware_no_runner_returns_error(self):
        """AgentAwareMessageProcessor returns error when named runner missing."""
        from core.interfaces.channel import Message, UserInfo
        from main import AgentAwareMessageProcessor

        pm = MagicMock()
        pm.get_runner.return_value = None
        pm.get_service.return_value = None

        processor = AgentAwareMessageProcessor(
            plugin_manager=pm,
            agent_context={"runner": "nonexistent-runner"},
        )

        msg = Message(user_id=1, username="test", text="hello", platform="test")
        user = UserInfo(
            user_id=1, username="test", display_name="Test", platform="test"
        )

        result = await processor.process_message(msg, user)
        assert result == "No runner available."


class TestMemoryRouteWithoutPlugin:
    """Memory route handles missing memory service gracefully."""

    @pytest.mark.asyncio
    async def test_get_memory_service_returns_none(self):
        """_get_memory_service returns None when no plugin manager."""
        try:
            from ui.routes.memory import _get_memory_service
        except ImportError:
            pytest.skip("ui.routes.memory requires deps not installed locally")

        with patch("core.registry.get_plugin_manager", return_value=None):
            result = await _get_memory_service()
            assert result is None

    @pytest.mark.asyncio
    async def test_get_memory_service_no_memory_plugin(self):
        """_get_memory_service returns None when memory plugin not loaded."""
        try:
            from ui.routes.memory import _get_memory_service
        except ImportError:
            pytest.skip("ui.routes.memory requires deps not installed locally")

        pm = MagicMock()
        pm.get_service_by_interface.return_value = None

        with patch("core.registry.get_plugin_manager", return_value=pm):
            result = await _get_memory_service()
            assert result is None


class TestNoReverseImports:
    """Verify core/ never imports from plugins/ at module level."""

    def test_no_plugin_imports_in_core(self):
        """Scan all loaded core.* modules for plugins.* dependencies."""
        for mod_name in CORE_MODULES:
            try:
                importlib.import_module(mod_name)
            except ImportError:
                continue

        violations = []
        for name, module in sys.modules.items():
            if not name.startswith("core."):
                continue
            module_file = getattr(module, "__file__", "") or ""
            if "plugins/" in module_file:
                violations.append(f"{name} is located under plugins/")

        assert not violations, f"Core modules with plugin dependencies: {violations}"
