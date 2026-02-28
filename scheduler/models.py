"""Task scheduler ORM models."""

from __future__ import annotations

from core.orm import Model, fields


class ScheduledTask(Model):
    """Persisted scheduled task."""

    _schema = "app"
    _name = "scheduled_tasks"

    user_id = fields.BigInteger(required=True)
    platform = fields.Text(required=True)
    schedule_type = fields.Text(required=True)
    cron = fields.Text()
    run_at = fields.Text()
    prompt = fields.Text(required=True)
    description = fields.Text()
    enabled = fields.Boolean(default=True)
    created_at = fields.DateTime(auto_now_add=True)
    last_run = fields.DateTime()
