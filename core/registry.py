"""Global registry for accessing core services.

Provides a clean way to access plugin_manager and other core services
from anywhere in the application without circular imports.
"""

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.agent_manager import AgentManager
    from core.database import DatabaseManager
    from core.models_registry import ModelsRegistry
    from core.plugin_manager import PluginManager
    from core.plugin_paths import PluginPathResolver

_plugin_manager: "PluginManager | None" = None
_agent_manager: "AgentManager | None" = None
_database: "DatabaseManager | None" = None
_path_resolver: "PluginPathResolver | None" = None
_models_registry: "ModelsRegistry | None" = None


def set_plugin_manager(pm: "PluginManager") -> None:
    """Register the plugin manager instance."""
    global _plugin_manager
    _plugin_manager = pm


def get_plugin_manager() -> "PluginManager | None":
    """Get the registered plugin manager instance."""
    return _plugin_manager


def get_available_mcp_servers() -> list[str]:
    """Get list of all available MCP server names.

    Returns empty list if no plugin_manager is registered or no providers.
    """
    if _plugin_manager is None:
        return []
    return _plugin_manager.get_all_mcp_server_names()


def get_mcp_config() -> dict:
    """Get current MCP configuration (generated in memory).

    Returns empty config if no plugin_manager is registered.
    """
    if _plugin_manager is None:
        return {"mcpServers": {}}
    return _plugin_manager.generate_mcp_config()


def get_mcp_provider(name: str):
    """Get MCP provider by name.

    Returns None if not found or no plugin_manager is registered.
    """
    if _plugin_manager is None:
        return None
    return _plugin_manager.mcp_providers.get(name)


def get_all_mcp_providers() -> dict:
    """Get all MCP providers.

    Returns empty dict if no plugin_manager is registered.
    """
    if _plugin_manager is None:
        return {}
    return _plugin_manager.mcp_providers


def set_agent_manager(am: "AgentManager") -> None:
    """Register the agent manager instance."""
    global _agent_manager
    _agent_manager = am


def get_agent_manager() -> "AgentManager | None":
    """Get the registered agent manager instance."""
    return _agent_manager


def set_database(db: "DatabaseManager") -> None:
    """Register the database manager instance."""
    global _database
    _database = db


def get_database() -> "DatabaseManager | None":
    """Get the registered database manager instance."""
    return _database


def set_path_resolver(resolver: "PluginPathResolver") -> None:
    """Register the plugin path resolver instance."""
    global _path_resolver
    _path_resolver = resolver


def get_path_resolver() -> "PluginPathResolver | None":
    """Get the registered plugin path resolver instance."""
    return _path_resolver


def set_models_registry(registry: "ModelsRegistry") -> None:
    """Register the models registry instance."""
    global _models_registry
    _models_registry = registry


def get_models_registry() -> "ModelsRegistry | None":
    """Get the registered models registry instance."""
    return _models_registry


def get_plugin_path(name: str) -> Path | None:
    """Convenience: resolve a plugin name to its directory path.

    Uses the registered PluginPathResolver if available,
    otherwise falls back to BASE_DIR/plugins/name.
    """
    if _path_resolver is not None:
        return _path_resolver.resolve(name)
    # Fallback for early boot or tests without resolver
    from config.settings import BASE_DIR

    fallback = BASE_DIR / "plugins" / name
    return fallback if fallback.exists() else None
