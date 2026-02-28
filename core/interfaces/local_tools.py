"""Local Tool Provider interface.

Allows plugins to expose MCP tools that are handled locally (not via external
MCP server process). The MCP gateway discovers these providers and integrates
their tools into the tools/list and tools/call flow.
"""

from abc import ABC, abstractmethod


class LocalToolProvider(ABC):
    """Plugin-provided local MCP tools (handled internally, not via external MCP server)."""

    @abstractmethod
    def get_server_name(self) -> str:
        """MCP server name for permission matching (e.g., 'videomaker')."""

    @abstractmethod
    def get_tools(self) -> list[dict]:
        """Return MCP tool definitions (inputSchema format)."""

    @abstractmethod
    async def handle_tool_call(
        self, tool_name: str, arguments: dict, **kwargs
    ) -> list[dict]:
        """Handle a tool call. Returns MCP content list.

        Args:
            tool_name: Full tool name including prefix (e.g., 'videomaker__create_project')
            arguments: Tool call arguments
            **kwargs: Additional context (agent_name, oauth2_user, etc.)

        Returns:
            List of MCP content dicts (e.g., [{"type": "text", "text": "..."}])
        """
