"""UI ORM models.

Declarative models for the admin UI:
- Notification: user notifications (OAuth expiry, MCP failure, plugin error, system)
"""

from __future__ import annotations

from core.orm import Model, fields


class Notification(Model):
    """User notification (OAuth expiry, MCP failure, plugin error, system event)."""

    _schema = "public"
    _name = "notifications"

    user_id = fields.Text(index=True)
    category = fields.Text(required=True)
    severity = fields.Text(required=True, default="info")
    title = fields.Text(required=True)
    message = fields.Text()
    source = fields.Text()
    is_read = fields.Boolean(default=False, index=True)
    action_url = fields.Text()
    expires_at = fields.DateTime()
    created_at = fields.DateTime(auto_now_add=True)
