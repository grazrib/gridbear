"""Admin auth ORM models.

Declarative models for authentication system:
- AdminUser: admin users with password hashes and TOTP secrets
- RecoveryCode: one-time recovery codes
- AdminSession: persistent login sessions
- AuditLog: security event log
- WebAuthnCredential: FIDO2/WebAuthn credentials
- UserToolPreference: per-user MCP tool toggles
- AgentToolPreference: per-agent MCP tool toggles
"""

from __future__ import annotations

from core.orm import Model, fields


class AdminUser(Model):
    """Admin user account."""

    _schema = "admin"
    _name = "users"

    username = fields.Text(required=True, unique=True)
    email = fields.Text()
    password_hash = fields.Text(required=True)
    totp_secret = fields.Text()
    totp_enabled = fields.Boolean(default=False)
    is_active = fields.Boolean(default=True)
    is_superadmin = fields.Boolean(default=False)
    unified_id = fields.Text(index=True)
    display_name = fields.Text()
    avatar_url = fields.Text()
    locale = fields.Text(default="en")
    webauthn_enabled = fields.Boolean(default=False)
    created_at = fields.DateTime(auto_now_add=True)
    last_login = fields.DateTime()
    failed_login_attempts = fields.Integer(default=0)
    lockout_until = fields.DateTime()


class RecoveryCode(Model):
    """One-time recovery code for 2FA bypass."""

    _schema = "admin"
    _name = "recovery_codes"

    user_id = fields.ForeignKey(AdminUser, on_delete="CASCADE")
    code_hash = fields.Text(required=True)
    used_at = fields.DateTime()
    created_at = fields.DateTime(auto_now_add=True)


class AdminSession(Model):
    """Persistent admin login session."""

    _schema = "admin"
    _name = "sessions"

    session_token = fields.Text(required=True, unique=True, index=True)
    user_id = fields.ForeignKey(AdminUser, on_delete="CASCADE")
    ip_address = fields.Text()
    user_agent = fields.Text()
    created_at = fields.DateTime(auto_now_add=True)
    expires_at = fields.DateTime(required=True)
    last_activity = fields.DateTime()


class AuditLog(Model):
    """Security event log entry."""

    _schema = "admin"
    _name = "audit_log"

    user_id = fields.Integer()
    username = fields.Text()
    event_type = fields.Text(required=True)
    ip_address = fields.Text()
    success = fields.Boolean()
    details = fields.Text()
    created_at = fields.DateTime(auto_now_add=True)


class WebAuthnCredential(Model):
    """FIDO2/WebAuthn credential."""

    _schema = "admin"
    _name = "webauthn_credentials"

    user_id = fields.ForeignKey(AdminUser, on_delete="CASCADE")
    credential_id = fields.Binary(required=True, unique=True)
    public_key = fields.Binary(required=True)
    sign_count = fields.Integer(default=0)
    device_name = fields.Text(default="Security Key")
    created_at = fields.DateTime(auto_now_add=True)
    last_used_at = fields.DateTime()


class UserToolPreference(Model):
    """Per-user MCP tool toggle."""

    _schema = "admin"
    _name = "user_tool_preferences"

    unified_id = fields.Text(required=True, index=True)
    tool_name = fields.Text(required=True)
    enabled = fields.Boolean(default=True)
    created_at = fields.DateTime(auto_now_add=True)
    _constraints = [
        ("uq_tool_prefs_uid_tool", "UNIQUE (unified_id, tool_name)"),
    ]


class AgentToolPreference(Model):
    """Per-agent MCP tool toggle (admin-managed)."""

    _schema = "admin"
    _name = "agent_tool_preferences"

    agent_name = fields.Text(required=True, index=True)
    tool_name = fields.Text(required=True)
    enabled = fields.Boolean(default=True)
    created_at = fields.DateTime(auto_now_add=True)
    _constraints = [
        ("uq_agent_tool_prefs", "UNIQUE (agent_name, tool_name)"),
    ]
