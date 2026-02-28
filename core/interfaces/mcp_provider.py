"""Base MCP Provider Interface.

Defines the abstract interface for MCP server providers (Gmail, Odoo, etc).
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.plugin_manager import PluginManager


class BaseMCPProvider(ABC):
    """Abstract interface for MCP server providers."""

    name: str = ""

    def __init__(self, config: dict):
        """Initialize provider with configuration.

        Args:
            config: Plugin configuration dict
        """
        self.config = config
        self._plugin_manager: "PluginManager | None" = None

    def set_plugin_manager(self, manager: "PluginManager") -> None:
        """Set reference to plugin manager.

        Args:
            manager: The plugin manager instance
        """
        self._plugin_manager = manager

    @abstractmethod
    def get_server_config(self) -> dict:
        """Get MCP server configuration (in-memory only, never written to disk).

        Returns:
            Dict with server configuration (command, args, env, etc)
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if MCP server is reachable.

        Returns:
            True if server is healthy
        """
        pass

    async def initialize(self) -> None:
        """Optional initialization setup."""
        pass

    async def shutdown(self) -> None:
        """Optional cleanup on shutdown."""
        pass

    def get_required_permissions(self) -> list[str]:
        """Permissions required to use this provider.

        Returns:
            List of permission identifiers
        """
        return [self.name]

    def get_server_names(self) -> list[str]:
        """Get list of MCP server names this provider creates.

        Some providers (like Gmail) create multiple servers.
        Default is single server with provider name.

        Returns:
            List of server names
        """
        return [self.name]

    def get_service_connections(self) -> list[dict]:
        """Declare service connections for user portal.

        Each dict describes a service users can connect to:
        {
            "id": "myservice",
            "name": "My Service",
            "auth_type": "oauth2_bearer" | "api_key" | "credentials",
            "description": "...",
            "icon": "fa-plug",
            "color": "blue",
        }

        Returns:
            List of connection descriptors. Default: empty (no user connections).
        """
        return []

    def get_user_server_config(self, unified_id: str, credentials: dict) -> dict:
        """Get server config with per-user credentials.

        Called instead of get_server_config() when user has connected
        credentials for this provider.

        Args:
            unified_id: User's unified ID
            credentials: User's stored credentials dict

        Returns:
            Server config dict. Default: falls back to global config.
        """
        return self.get_server_config()

    def get_oauth_config(self, connection_id: str) -> dict | None:
        """Get OAuth configuration for a service connection.

        Returns:
            Dict with authorize_url, token_url, client_id, client_secret, scopes.
            None if the plugin handles OAuth internally.
        """
        return None
