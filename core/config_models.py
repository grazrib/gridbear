"""ORM models for user/channel configuration (replaces admin_config.json).

Normalized tables under the ``app`` schema store what was previously
a single JSON file: authorized channel users, cross-platform identities
(UserPlatform with FK to User), MCP permissions (per-user and per-group),
memory groups, service accounts, and temporary OAuth tokens.

Global scalar settings (bot_identity, bot_email_settings, webchat_tts_provider)
live in the existing ``SystemConfig`` key-value table.
"""

from __future__ import annotations

from core.models.user import User
from core.orm import Model, fields


class ChannelAuthorizedUser(Model):
    """Users authorized to interact with a specific channel (telegram, discord, etc.)."""

    _schema = "app"
    _name = "channel_authorized_users"

    channel = fields.Text(required=True, index=True)
    platform_user_id = fields.BigInteger()
    username = fields.Text()
    created_at = fields.DateTime(auto_now_add=True)

    _constraints = [
        ("uq_ch_auth", "UNIQUE (channel, platform_user_id, username)"),
    ]


class UserPlatform(Model):
    """FK-based cross-platform identity mapping (replaces UserIdentity)."""

    _schema = "app"
    _name = "user_platforms"
    _tenant_field = None

    user_id = fields.ForeignKey(User, on_delete="CASCADE", required=True, index=True)
    platform = fields.Text(required=True)
    platform_username = fields.Text(required=True)

    _constraints = [
        ("uq_user_platform", "UNIQUE (user_id, platform)"),
        ("uq_platform_username", "UNIQUE (platform, platform_username)"),
    ]


class UserMcpPermission(Model):
    """Per-user MCP server permissions."""

    _schema = "app"
    _name = "user_mcp_permissions"

    username = fields.Text(required=True, index=True)
    server_name = fields.Text(required=True)
    unified_id = fields.Text(index=True)

    _constraints = [
        ("uq_user_mcp_uid", "UNIQUE (unified_id, server_name)"),
    ]


class MemoryGroup(Model):
    """Shared-memory groups: users in the same group share memory context."""

    _schema = "app"
    _name = "memory_groups"

    group_name = fields.Text(required=True, index=True)
    unified_id = fields.Text(required=True)

    _constraints = [
        ("uq_mem_grp", "UNIQUE (group_name, unified_id)"),
    ]


class GroupMcpPermission(Model):
    """Per-group MCP server permissions."""

    _schema = "app"
    _name = "group_mcp_permissions"

    group_name = fields.Text(required=True, index=True)
    server_name = fields.Text(required=True)

    _constraints = [
        ("uq_grp_mcp", "UNIQUE (group_name, server_name)"),
    ]


class UserServiceAccount(Model):
    """External service accounts linked to a user (gmail, ms365, etc.)."""

    _schema = "app"
    _name = "user_service_accounts"

    unified_id = fields.Text(required=True, index=True)
    service_type = fields.Text(required=True)
    account_id = fields.Text(required=True)

    _constraints = [
        ("uq_svc_acct", "UNIQUE (unified_id, service_type, account_id)"),
    ]


class PasswordToken(Model):
    """Tokens for user invites and password resets."""

    _schema = "app"
    _name = "password_tokens"
    _tenant_field = None

    user_id = fields.ForeignKey(User, on_delete="CASCADE", required=True, index=True)
    token_hash = fields.Text(required=True)
    purpose = fields.Text(required=True)  # "invite" or "reset"
    expires_at = fields.DateTime(required=True)
    used_at = fields.DateTime()
    created_at = fields.DateTime(auto_now_add=True)


class OAuthToken(Model):
    """Temporary tokens for OAuth2 authorization flows (TTL ~1 hour)."""

    _schema = "app"
    _name = "oauth_tokens"

    token = fields.Text(required=True, unique=True, index=True)
    unified_id = fields.Text(required=True)
    created_at = fields.DateTime(auto_now_add=True)
