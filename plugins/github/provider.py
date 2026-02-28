"""GitHub MCP Provider Plugin.

Uses the official GitHub MCP server (ghcr.io/github/github-mcp-server).
Token stored in secrets_manager with key "github_token".
"""

from config.logging_config import logger
from core.interfaces.mcp_provider import BaseMCPProvider
from ui.secrets_manager import secrets_manager


class GitHubMCPProvider(BaseMCPProvider):
    """GitHub MCP server provider using official GitHub server."""

    name = "github"
    SECRET_KEY = "GITHUB_TOKEN"

    def __init__(self, config: dict):
        super().__init__(config)
        self.toolsets = config.get("toolsets", "all")
        self.read_only = config.get("read_only", False)

    async def initialize(self) -> None:
        """Initialize provider."""
        token = self._get_token()
        if token:
            logger.info("GitHub MCP provider initialized with token")
        else:
            logger.warning(
                "GitHub MCP provider: no token configured (add via admin UI)"
            )

    async def shutdown(self) -> None:
        """Cleanup resources."""
        pass

    def _get_token(self) -> str:
        """Get GitHub token from secrets_manager (empty string if not set)."""
        return secrets_manager.get_plain(self.SECRET_KEY)

    @staticmethod
    def store_token(token: str) -> None:
        """Store GitHub token in secrets_manager."""
        secrets_manager.set(GitHubMCPProvider.SECRET_KEY, token)
        logger.info("Stored GitHub token in secrets")

    @staticmethod
    def delete_token() -> None:
        """Delete GitHub token from secrets_manager."""
        secrets_manager.delete(GitHubMCPProvider.SECRET_KEY)
        logger.info("Deleted GitHub token from secrets")

    @staticmethod
    def has_token() -> bool:
        """Check if GitHub token exists."""
        return secrets_manager.get(GitHubMCPProvider.SECRET_KEY) is not None

    def get_server_config(self) -> dict:
        """Get MCP server configuration for official GitHub server.

        Uses binary: /usr/local/bin/github-mcp-server
        """
        token = self._get_token()
        if not token:
            logger.error("GitHub MCP: no token available")
            return {}

        env = {
            "GITHUB_PERSONAL_ACCESS_TOKEN": token,
        }

        if self.toolsets and self.toolsets != "all":
            env["GITHUB_TOOLSETS"] = self.toolsets

        if self.read_only:
            env["GITHUB_READ_ONLY"] = "true"

        return {
            "github": {
                "command": "/usr/local/bin/github-mcp-server",
                "args": ["stdio"],
                "env": env,
            }
        }

    async def health_check(self) -> bool:
        """Check if GitHub MCP server is available."""
        return bool(self._get_token())

    def get_required_permissions(self) -> list[str]:
        """Permissions required to use this provider."""
        return ["github"]

    def get_server_names(self) -> list[str]:
        """Get list of MCP server names this provider creates."""
        return ["github"]
