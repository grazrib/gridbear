"""Gmail MCP Provider Plugin.

Provides Gmail MCP server configuration for multiple accounts.
Tokens are stored encrypted in secrets.db and passed via env var at runtime.
"""

import json
from pathlib import Path

from config.logging_config import logger
from core.interfaces.mcp_provider import BaseMCPProvider
from ui.config_manager import ConfigManager
from ui.secrets_manager import secrets_manager

from .context_service import GmailContextService


class GmailProvider(BaseMCPProvider):
    """Gmail MCP server provider (multi-account)."""

    name = "gmail"

    def __init__(self, config: dict):
        super().__init__(config)
        # Python server embedded in plugin
        self.server_path = Path(__file__).parent / "server.py"
        self.download_dir = config.get("download_dir", "/app/data/attachments")
        self._server_names: list[str] = []

    async def initialize(self) -> None:
        """Initialize provider and discover accounts."""
        config_manager = ConfigManager()
        self._gmail_accounts = config_manager.get_gmail_accounts()
        # Build server names using email addresses (to match permission format)
        self._server_names = []
        for unified_id, emails in self._gmail_accounts.items():
            for email in emails:
                # Only add if token exists
                token_data = self._get_token_for_email(email)
                if token_data:
                    self._server_names.append(f"gmail-{email}")
                else:
                    logger.warning(f"Gmail account {email} has no token configured")

        # Initialize context service for email/event tracking
        self._context_service = GmailContextService({"download_dir": self.download_dir})
        await self._context_service.initialize()

        logger.info(
            f"Gmail MCP provider initialized with {len(self._server_names)} accounts"
        )

    async def shutdown(self) -> None:
        """Cleanup resources."""
        if hasattr(self, "_context_service") and self._context_service:
            await self._context_service.shutdown()

    def _get_token_for_email(self, email: str) -> dict | None:
        """Get decrypted OAuth token data for email account.

        Returns None if token not found.
        """
        secret_key = f"gmail_token_{email}"
        token_json = secrets_manager.get_plain(secret_key)
        if not token_json:
            return None
        try:
            return json.loads(token_json)
        except json.JSONDecodeError:
            logger.error(f"Invalid token JSON for {email}")
            return None

    def get_server_config(self) -> dict:
        """Get MCP server configurations for all Gmail accounts.

        Returns a dict mapping server names to their configurations.
        Token is passed via GMAIL_TOKEN_DATA environment variable.
        """
        config_manager = ConfigManager()
        gmail_accounts = config_manager.get_gmail_accounts()

        servers = {}
        for unified_id, emails in gmail_accounts.items():
            for email in emails:
                token_data = self._get_token_for_email(email)
                if not token_data:
                    continue

                server_name = f"gmail-{email}"
                servers[server_name] = {
                    "command": "python",
                    "args": [str(self.server_path)],
                    "env": {
                        "GMAIL_TOKEN_DATA": json.dumps(token_data),
                        "GMAIL_DOWNLOAD_DIR": self.download_dir,
                    },
                }

        return servers

    async def health_check(self) -> bool:
        """Check if Gmail MCP server is available."""
        return self.server_path.exists()

    def get_required_permissions(self) -> list[str]:
        """Permissions required to use this provider.

        For Gmail, each account requires its own permission.
        """
        return self._server_names

    def get_server_names(self) -> list[str]:
        """Get list of MCP server names this provider creates."""
        return self._server_names

    @staticmethod
    def store_token(email: str, token_data: dict) -> None:
        """Store OAuth token encrypted in secrets db.

        Args:
            email: Gmail account email address
            token_data: OAuth token data (access_token, refresh_token, etc.)
        """
        secret_key = f"gmail_token_{email}"
        secrets_manager.set(secret_key, json.dumps(token_data))
        logger.info(f"Stored encrypted token for {email}")

    @staticmethod
    def delete_token(email: str) -> None:
        """Delete OAuth token from secrets db."""
        secret_key = f"gmail_token_{email}"
        secrets_manager.delete(secret_key)
        logger.info(f"Deleted token for {email}")

    @staticmethod
    def has_token(email: str) -> bool:
        """Check if token exists for email."""
        secret_key = f"gmail_token_{email}"
        return secrets_manager.get(secret_key) is not None
