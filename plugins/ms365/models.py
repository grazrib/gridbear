"""MS365 ORM models."""

from __future__ import annotations

from core.orm import Model, fields


class MS365Token(Model):
    """OAuth token storage for MS365/Azure AD tenants."""

    _schema = "vault"
    _name = "ms365_tokens"
    _primary_key = "tenant_id"

    tenant_id = fields.Text(required=True)
    tenant_name = fields.Text()
    access_token_encrypted = fields.Binary()
    refresh_token_encrypted = fields.Binary()
    expires_at = fields.DateTime()
    scopes = fields.Text()
    capabilities = fields.Text()
    capabilities_cached_at = fields.DateTime()
    role = fields.Text(default="guest")
    status = fields.Text(default="active")
    failure_count = fields.Integer(default=0)
    schema_version = fields.Integer(default=1)
    created_at = fields.DateTime(auto_now_add=True)
    updated_at = fields.DateTime(auto_now_add=True, auto_now=True)
