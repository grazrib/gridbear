"""Configuration manager — DB-backed facade (replaces file-based JSON).

All method signatures are preserved so that existing route handlers
(permissions.py, users.py, memory.py, settings.py, auth.py, me.py, etc.)
continue to work without modification.
"""

import shutil
from datetime import datetime, timedelta
from pathlib import Path

from core.config_models import (
    ChannelAuthorizedUser,
    GroupMcpPermission,
    MemoryGroup,
    OAuthToken,
    UserMcpPermission,
    UserPlatform,
    UserServiceAccount,
)
from core.models.user import User
from core.system_config import SystemConfig

BASE_DIR = Path(__file__).resolve().parent.parent
CREDENTIALS_DIR = BASE_DIR / "credentials"

# OAuth tokens expire after 1 hour
OAUTH_TOKEN_TTL_HOURS = 1


class ConfigManager:
    """Manages dynamic configuration for GridBear admin panel."""

    def __init__(self):
        pass

    # ── Channel users (generic) ─────────────────────────────────

    def get_channel_users(self, channel: str) -> dict:
        """Get authorized users for a channel.

        Returns:
            Dict with 'ids' and 'usernames' lists
        """
        rows = ChannelAuthorizedUser.search_sync([("channel", "=", channel)])
        return {
            "ids": [
                r.get("platform_user_id") for r in rows if r.get("platform_user_id")
            ],
            "usernames": [r.get("username") for r in rows if r.get("username")],
        }

    def add_channel_user(self, channel: str, user_id: int = None, username: str = None):
        """Add an authorized user to a channel."""
        if user_id:
            existing = ChannelAuthorizedUser.search_sync(
                [("channel", "=", channel), ("platform_user_id", "=", user_id)]
            )
            if not existing:
                ChannelAuthorizedUser.create_sync(
                    channel=channel, platform_user_id=user_id
                )
        if username:
            username = username.lower().lstrip("@")
            existing = ChannelAuthorizedUser.search_sync(
                [("channel", "=", channel), ("username", "=", username)]
            )
            if not existing:
                ChannelAuthorizedUser.create_sync(channel=channel, username=username)

    def remove_channel_user(
        self, channel: str, user_id: int = None, username: str = None
    ):
        """Remove an authorized user from a channel."""
        if user_id:
            ChannelAuthorizedUser.delete_multi_sync(
                [("channel", "=", channel), ("platform_user_id", "=", user_id)]
            )
        if username:
            username = username.lower().lstrip("@")
            ChannelAuthorizedUser.delete_multi_sync(
                [("channel", "=", channel), ("username", "=", username)]
            )

    # ── Gmail accounts (unified_id -> list of emails) ───────────

    def get_gmail_accounts(self) -> dict[str, list[str]]:
        """Get gmail accounts keyed by unified_id."""
        rows = UserServiceAccount.search_sync([("service_type", "=", "gmail")])
        result: dict[str, list[str]] = {}
        for r in rows:
            uid = r["unified_id"]
            result.setdefault(uid, []).append(r["account_id"])
        return result

    def add_gmail_account(self, unified_id: str, email: str):
        """Add Gmail account linked to unified identity."""
        unified_id = unified_id.lower()
        existing = UserServiceAccount.search_sync(
            [
                ("unified_id", "=", unified_id),
                ("service_type", "=", "gmail"),
                ("account_id", "=", email),
            ]
        )
        if not existing:
            UserServiceAccount.create_sync(
                unified_id=unified_id, service_type="gmail", account_id=email
            )

    def remove_gmail_account(self, unified_id: str, email: str = None):
        """Remove Gmail account from unified identity."""
        unified_id = unified_id.lower()

        if email:
            UserServiceAccount.delete_multi_sync(
                [
                    ("unified_id", "=", unified_id),
                    ("service_type", "=", "gmail"),
                    ("account_id", "=", email),
                ]
            )
            cred_path = CREDENTIALS_DIR / email
            if cred_path.exists():
                shutil.rmtree(cred_path)
        else:
            # Remove all gmail accounts for this user
            rows = UserServiceAccount.search_sync(
                [
                    ("unified_id", "=", unified_id),
                    ("service_type", "=", "gmail"),
                ]
            )
            for r in rows:
                cred_path = CREDENTIALS_DIR / r["account_id"]
                if cred_path.exists():
                    shutil.rmtree(cred_path)
            UserServiceAccount.delete_multi_sync(
                [
                    ("unified_id", "=", unified_id),
                    ("service_type", "=", "gmail"),
                ]
            )

    # ── OAuth tokens (temporary with expiration) ────────────────

    def create_oauth_token(self, unified_id: str) -> str:
        """Create temporary token for OAuth flow with expiration."""
        import secrets

        token = secrets.token_urlsafe(32)
        OAuthToken.create_sync(token=token, unified_id=unified_id.lower())
        self._cleanup_expired_oauth_tokens()
        return token

    def get_oauth_token_data(self, token: str) -> dict | None:
        """Get token data if valid and not expired."""
        row = OAuthToken.get_sync(token=token)
        if not row:
            return None
        created_at = row.get("created_at")
        if created_at:
            if isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at)
            cutoff = datetime.now(tz=created_at.tzinfo) - timedelta(
                hours=OAUTH_TOKEN_TTL_HOURS
            )
            if created_at < cutoff:
                self.delete_oauth_token(token)
                return None
        return {"unified_id": row["unified_id"], "created_at": str(created_at)}

    def _cleanup_expired_oauth_tokens(self):
        """Remove expired OAuth tokens."""
        rows = OAuthToken.search_sync()
        cutoff = datetime.now(tz=None) - timedelta(hours=OAUTH_TOKEN_TTL_HOURS)
        for r in rows:
            created_at = r.get("created_at")
            if not created_at:
                OAuthToken.delete_sync(r["id"])
                continue
            if isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at)
            # Compare as naive if needed
            naive_created = (
                created_at.replace(tzinfo=None) if created_at.tzinfo else created_at
            )
            if naive_created < cutoff:
                OAuthToken.delete_sync(r["id"])

    def delete_oauth_token(self, token: str):
        row = OAuthToken.get_sync(token=token)
        if row:
            OAuthToken.delete_sync(row["id"])

    # ── Admin password (kept for backward compat, deprecated) ───

    def get_password_hash(self) -> str:
        return SystemConfig.get_param_sync("admin_password_hash", "")

    def set_password_hash(self, password_hash: str):
        SystemConfig.set_param_sync("admin_password_hash", password_hash)

    # ── User MCP permissions ────────────────────────────────────

    def get_user_permissions(self, unified_id: str) -> list[str] | None:
        """Get MCP servers allowed for user. None = not configured (use default)."""
        unified_id = unified_id.lower()
        rows = UserMcpPermission.search_sync([("unified_id", "=", unified_id)])
        if not rows:
            return None
        return [r["server_name"] for r in rows]

    def get_all_user_permissions(self) -> dict[str, list[str]]:
        """Get all user permissions keyed by unified_id."""
        rows = UserMcpPermission.search_sync()
        result: dict[str, list[str]] = {}
        for r in rows:
            result.setdefault(r["unified_id"], []).append(r["server_name"])
        return result

    def set_user_permissions(self, unified_id: str, servers: list[str]):
        """Set MCP servers allowed for user (replace all)."""
        unified_id = unified_id.lower()
        UserMcpPermission.delete_multi_sync([("unified_id", "=", unified_id)])
        for server in servers:
            UserMcpPermission.create_sync(
                username=unified_id,
                unified_id=unified_id,
                server_name=server,
            )

    def delete_user_permissions(self, unified_id: str):
        """Remove user permissions (reverts to default)."""
        unified_id = unified_id.lower()
        UserMcpPermission.delete_multi_sync([("unified_id", "=", unified_id)])

    def get_available_mcp_servers(self) -> list[str]:
        """Get list of all configured MCP servers from plugin registry."""
        from core.registry import get_available_mcp_servers

        return get_available_mcp_servers()

    # ── User identities (cross-platform linking) ────────────────

    def _resolve_user_id(self, username: str) -> int | None:
        """Resolve username to User.id."""
        user = User.get_sync(username=username.lower())
        return user["id"] if user else None

    def _resolve_username(self, user_id: int) -> str | None:
        """Resolve User.id to username."""
        user = User.get_sync(id=user_id)
        return user["username"] if user else None

    def get_user_identities(self) -> dict[str, dict[str, str]]:
        """Get all user identities: {username: {platform: platform_username}}."""
        rows = UserPlatform.search_sync()
        # Build user_id → username cache
        user_ids = {r["user_id"] for r in rows}
        id_to_username: dict[int, str] = {}
        for uid in user_ids:
            uname = self._resolve_username(uid)
            if uname:
                id_to_username[uid] = uname

        result: dict[str, dict[str, str]] = {}
        for r in rows:
            username = id_to_username.get(r["user_id"])
            if username:
                result.setdefault(username, {})[r["platform"]] = r["platform_username"]
        return result

    def get_all_unified_ids(self) -> list[str]:
        """Get list of all usernames that have platform links."""
        rows = UserPlatform.search_sync()
        user_ids = {r["user_id"] for r in rows}
        usernames = []
        for uid in user_ids:
            uname = self._resolve_username(uid)
            if uname:
                usernames.append(uname)
        return usernames

    def get_unified_user_id(self, platform: str, username: str) -> str | None:
        """Get unified user ID (username) from platform and platform_username."""
        username = username.lower().lstrip("@")
        platform = platform.lower()
        row = UserPlatform.get_sync(platform=platform, platform_username=username)
        if row:
            return self._resolve_username(row["user_id"])
        return None

    def get_channel_username(self, unified_id: str, channel: str) -> str | None:
        """Get channel-specific username from unified ID."""
        user_id = self._resolve_user_id(unified_id)
        if not user_id:
            return None
        row = UserPlatform.get_sync(user_id=user_id, platform=channel.lower())
        return row["platform_username"] if row else None

    def add_user_identity(self, unified_id: str, platform: str, username: str):
        """Link a platform username to a user."""
        user_id = self._resolve_user_id(unified_id)
        if not user_id:
            return
        platform = platform.lower()
        username = username.lower().lstrip("@")

        UserPlatform.create_or_update_sync(
            _conflict_fields=("user_id", "platform"),
            _update_fields=["platform_username"],
            user_id=user_id,
            platform=platform,
            platform_username=username,
        )

    def remove_user_identity(self, unified_id: str, platform: str = None):
        """Remove user identity or specific platform link."""
        user_id = self._resolve_user_id(unified_id)
        if not user_id:
            return

        if platform:
            platform = platform.lower()
            UserPlatform.delete_multi_sync(
                [("user_id", "=", user_id), ("platform", "=", platform)]
            )
        else:
            UserPlatform.delete_multi_sync([("user_id", "=", user_id)])

    # ── Memory groups ───────────────────────────────────────────

    def get_memory_groups(self) -> dict[str, list[str]]:
        """Get all memory groups: {group_name: [unified_ids]}."""
        rows = MemoryGroup.search_sync()
        result: dict[str, list[str]] = {}
        for r in rows:
            result.setdefault(r["group_name"], []).append(r["unified_id"])
        return result

    def get_user_memory_group(self, unified_id: str) -> str | None:
        """Get the memory group a user belongs to."""
        unified_id = unified_id.lower()
        rows = MemoryGroup.search_sync()
        for r in rows:
            if r["unified_id"].lower() == unified_id:
                return r["group_name"]
        return None

    def get_memory_group_members(self, group_name: str) -> list[str]:
        """Get all members of a memory group."""
        rows = MemoryGroup.search_sync([("group_name", "=", group_name.lower())])
        return [r["unified_id"] for r in rows]

    def add_memory_group(self, group_name: str, members: list[str]):
        """Create or update a memory group."""
        group_name = group_name.lower()
        members = [m.lower() for m in members]

        # Replace existing members
        MemoryGroup.delete_multi_sync([("group_name", "=", group_name)])
        for member in members:
            MemoryGroup.create_sync(group_name=group_name, unified_id=member)

    def add_user_to_memory_group(self, group_name: str, unified_id: str):
        """Add a user to a memory group."""
        group_name = group_name.lower()
        unified_id = unified_id.lower()
        existing = MemoryGroup.search_sync(
            [("group_name", "=", group_name), ("unified_id", "=", unified_id)]
        )
        if not existing:
            MemoryGroup.create_sync(group_name=group_name, unified_id=unified_id)

    def remove_user_from_memory_group(self, group_name: str, unified_id: str):
        """Remove a user from a memory group."""
        group_name = group_name.lower()
        unified_id = unified_id.lower()
        MemoryGroup.delete_multi_sync(
            [("group_name", "=", group_name), ("unified_id", "=", unified_id)]
        )

    def delete_memory_group(self, group_name: str):
        """Delete a memory group."""
        group_name = group_name.lower()
        MemoryGroup.delete_multi_sync([("group_name", "=", group_name)])

    # ── Group MCP permissions ───────────────────────────────────

    def get_group_permissions(self, group_name: str) -> list[str]:
        """Get MCP servers allowed for a group."""
        rows = GroupMcpPermission.search_sync([("group_name", "=", group_name.lower())])
        return [r["server_name"] for r in rows]

    def get_all_group_permissions(self) -> dict[str, list[str]]:
        """Get all group permissions."""
        rows = GroupMcpPermission.search_sync()
        result: dict[str, list[str]] = {}
        for r in rows:
            result.setdefault(r["group_name"], []).append(r["server_name"])
        return result

    def set_group_permissions(self, group_name: str, servers: list[str]):
        """Set MCP servers allowed for a group."""
        group_name = group_name.lower()
        GroupMcpPermission.delete_multi_sync([("group_name", "=", group_name)])
        for server in servers:
            GroupMcpPermission.create_sync(group_name=group_name, server_name=server)

    def delete_group_permissions(self, group_name: str):
        """Remove group permissions."""
        group_name = group_name.lower()
        GroupMcpPermission.delete_multi_sync([("group_name", "=", group_name)])

    def get_group_gmail_accounts(self, unified_id: str) -> dict[str, list[str]]:
        """Get all Gmail accounts for users in the same memory groups."""
        unified_id = unified_id.lower()

        # Find all groups this user belongs to and merge members
        group_members = {unified_id}
        all_groups = MemoryGroup.search_sync()
        for r in all_groups:
            if r["unified_id"].lower() == unified_id:
                # User is in this group — add all members
                for r2 in all_groups:
                    if r2["group_name"] == r["group_name"]:
                        group_members.add(r2["unified_id"].lower())

        # Get gmail accounts for each member
        result: dict[str, list[str]] = {}
        for member_id in group_members:
            rows = UserServiceAccount.search_sync(
                [
                    ("unified_id", "=", member_id),
                    ("service_type", "=", "gmail"),
                ]
            )
            if rows:
                result[member_id] = [r["account_id"] for r in rows]
        return result

    # ── User locales ────────────────────────────────────────────

    def get_user_locales(self) -> dict[str, str]:
        """Get all user locale preferences: {username: locale}."""
        rows = User.search_sync()
        return {r["username"]: r.get("locale", "en") for r in rows if r["username"]}

    def get_user_locale(self, unified_id: str) -> str:
        """Get user's locale preference. Returns 'en' as default."""
        row = User.get_sync(username=unified_id.lower())
        if row:
            return row.get("locale") or "en"
        return "en"

    def set_user_locale(self, unified_id: str, locale: str):
        """Set user's locale preference."""
        locale = locale.lower().strip()
        row = User.get_sync(username=unified_id.lower())
        if row:
            User.write_sync(row["id"], locale=locale)

    def delete_user_locale(self, unified_id: str):
        """Remove user locale (reverts to default 'en')."""
        row = User.get_sync(username=unified_id.lower())
        if row:
            User.write_sync(row["id"], locale="en")

    def get_available_locales(self) -> list[str]:
        """Get list of available locales based on translation files."""
        locales = ["en"]
        i18n_dir = BASE_DIR / "core" / "i18n"
        if i18n_dir.exists():
            for po_file in i18n_dir.glob("*.po"):
                locale = po_file.stem
                if locale not in locales:
                    locales.append(locale)
        return sorted(locales)

    # ── Bot identity settings ───────────────────────────────────

    def get_bot_identity(self) -> str | None:
        """Get the identity configured as the bot."""
        return SystemConfig.get_param_sync("bot_identity")

    def set_bot_identity(self, unified_id: str | None):
        """Set which identity is the bot."""
        if unified_id:
            SystemConfig.set_param_sync("bot_identity", unified_id.lower())
        else:
            SystemConfig.set_param_sync("bot_identity", None)

    # ── WebChat TTS provider ────────────────────────────────────

    def get_webchat_tts_provider(self) -> str:
        """Get the TTS provider for webchat. Returns 'browser' as default."""
        return SystemConfig.get_param_sync("webchat_tts_provider", "browser")

    def set_webchat_tts_provider(self, provider: str):
        """Set the TTS provider for webchat."""
        SystemConfig.set_param_sync("webchat_tts_provider", provider)

    # ── Bot email settings ──────────────────────────────────────

    def get_bot_email_settings(self) -> dict:
        """Get bot email monitoring settings."""
        default = {
            "check_interval_minutes": 5,
            "label": "INBOX",
            "enabled": False,
            "instructions": "",
            "auto_reply": False,
        }
        return SystemConfig.get_param_sync("bot_email_settings", default)

    def set_bot_email_settings(self, settings: dict):
        """Set bot email monitoring settings."""
        SystemConfig.set_param_sync("bot_email_settings", settings)
