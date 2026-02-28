"""Google Workspace MCP Provider Plugin.

Provides Google Workspace MCP server configuration for multiple accounts.
Shares OAuth tokens with Gmail plugin (stored encrypted in secrets.db).
"""

import json
import re
from pathlib import Path

from config.logging_config import logger
from core.interfaces.mcp_provider import BaseMCPProvider
from ui.config_manager import ConfigManager
from ui.secrets_manager import secrets_manager

from .context_service import GoogleWorkspaceContextService

CLAUDE_SETTINGS_PATH = Path("/root/.claude/settings.json")

REQUIRED_SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.readonly",
]


def _add_gws_tool_permission(email: str) -> bool:
    """Add Google Workspace tool permission to Claude Code settings.json."""
    sanitized = re.sub(r"[@.]", "_", email)
    permission_pattern = f"mcp__gws-{sanitized}__*"

    try:
        if not CLAUDE_SETTINGS_PATH.exists():
            return False

        with open(CLAUDE_SETTINGS_PATH, "r") as f:
            settings = json.load(f)

        if "permissions" not in settings:
            settings["permissions"] = {}
        if "allow" not in settings["permissions"]:
            settings["permissions"]["allow"] = []

        if permission_pattern in settings["permissions"]["allow"]:
            return False

        settings["permissions"]["allow"].append(permission_pattern)

        with open(CLAUDE_SETTINGS_PATH, "w") as f:
            json.dump(settings, f, indent=2)

        return True
    except Exception:
        return False


class GoogleWorkspaceProvider(BaseMCPProvider):
    """Google Workspace MCP server provider (multi-account)."""

    name = "google-workspace"

    def __init__(self, config: dict):
        super().__init__(config)
        self.server_path = Path(__file__).parent / "server.py"
        self.export_dir = config.get("export_dir", "/app/data/exports")
        self._server_names: list[str] = []

    async def initialize(self) -> None:
        """Initialize provider and discover accounts with Workspace scopes."""
        config_manager = ConfigManager()
        gmail_accounts = config_manager.get_gmail_accounts()

        self._server_names = []
        for unified_id, emails in gmail_accounts.items():
            for email in emails:
                token_data = self._get_token_for_email(email)
                if token_data and self._has_workspace_scopes(token_data):
                    self._server_names.append(f"gws-{email}")
                    _add_gws_tool_permission(email)
                elif token_data:
                    logger.info(
                        f"Gmail account {email} lacks Workspace scopes, "
                        "user needs to re-authorize"
                    )

        # Initialize context service for working document tracking
        self._context_service = GoogleWorkspaceContextService(
            {"export_dir": self.export_dir}
        )
        await self._context_service.initialize()

        logger.info(
            f"Google Workspace MCP provider initialized with "
            f"{len(self._server_names)} accounts"
        )

    async def shutdown(self) -> None:
        """Cleanup resources."""
        if hasattr(self, "_context_service") and self._context_service:
            await self._context_service.shutdown()

    def _get_token_for_email(self, email: str) -> dict | None:
        """Get decrypted OAuth token data for email account.

        Uses same tokens as Gmail plugin (gmail_token_{email}).
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

    def _has_workspace_scopes(self, token_data: dict) -> bool:
        """Check if token has required Workspace scopes."""
        token_scopes = set(token_data.get("scopes", []))
        required = set(REQUIRED_SCOPES)
        return required.issubset(token_scopes)

    def get_server_config(self) -> dict:
        """Get MCP server configurations for all accounts with Workspace scopes.

        Returns a dict mapping server names to their configurations.
        Token is passed via GWORKSPACE_TOKEN_DATA environment variable.
        """
        config_manager = ConfigManager()
        gmail_accounts = config_manager.get_gmail_accounts()

        servers = {}
        for unified_id, emails in gmail_accounts.items():
            for email in emails:
                token_data = self._get_token_for_email(email)
                if not token_data:
                    continue

                if not self._has_workspace_scopes(token_data):
                    continue

                server_name = f"gws-{email}"
                servers[server_name] = {
                    "command": "python",
                    "args": [str(self.server_path)],
                    "env": {
                        "GWORKSPACE_TOKEN_DATA": json.dumps(token_data),
                        "GWORKSPACE_EXPORT_DIR": self.export_dir,
                    },
                }

        return servers

    async def health_check(self) -> bool:
        """Check if Google Workspace MCP server is available."""
        return self.server_path.exists()

    def get_required_permissions(self) -> list[str]:
        """Permissions required to use this provider.

        Each account requires its own permission.
        """
        return self._server_names

    def get_server_names(self) -> list[str]:
        """Get list of MCP server names this provider creates."""
        return self._server_names

    def get_allowed_tools(self) -> list[str]:
        """Tools to allow in Claude CLI for all Workspace accounts."""
        tools = []
        tool_names = [
            "docs_create",
            "docs_read",
            "docs_update",
            "docs_export",
            "docs_replace",
            "docs_clear",
            "docs_append",
            "docs_read_tables",
            "docs_update_table_cell",
            "docs_find_table_by_text",
            "docs_update_table_row",
            "docs_export_image",
            "docs_delete_table",
            "docs_update_text_style",
            "docs_update_table_cell_style",
            "docs_insert_toc",
            "docs_insert_table",
            "docs_insert_table_row",
            "docs_insert_table_column",
            "docs_delete_table_row",
            "docs_delete_table_column",
            "docs_insert_image",
            "docs_update_paragraph_style",
            "docs_create_bullets",
            "docs_delete_bullets",
            "docs_insert_page_break",
            "docs_create_header",
            "docs_create_footer",
            "docs_insert_link",
            "docs_remove_link",
            "sheets_create",
            "sheets_read",
            "sheets_write",
            "sheets_append",
            "sheets_clear",
            "sheets_add_sheet",
            "slides_create",
            "slides_read",
            "slides_add_slide",
            "slides_update",
            "drive_copy",
            "drive_delete",
            "drive_move",
            "drive_rename",
            "drive_create_folder",
            "drive_share",
            "drive_list",
            "drive_upload",
        ]
        for server_name in self._server_names:
            # gws-email@domain.com -> gws-email_domain_com
            sanitized = re.sub(r"[@.]", "_", server_name)
            for tool in tool_names:
                tools.append(f"mcp__{sanitized}__{tool}")
        return tools
