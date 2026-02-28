"""ORM model for plugin state registry."""

from __future__ import annotations

from core.orm import Model, fields


class PluginRegistryEntry(Model):
    """Tracks plugin install state in PostgreSQL.

    States:
      - available: on disk, never installed
      - installed: configured (may be enabled or disabled)
      - not_available: was known but directory gone from disk
    """

    _schema = "app"
    _name = "plugin_registry"

    name = fields.Text(required=True, unique=True, index=True)
    state = fields.Text(required=True, default="available")
    enabled = fields.Boolean(default=False)
    version = fields.Text()
    plugin_type = fields.Text()
    manifest_hash = fields.Text()
    config = fields.Json(default={})
    installed_at = fields.DateTime()
    updated_at = fields.DateTime(auto_now_add=True, auto_now=True)
