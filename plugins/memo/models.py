"""Memo plugin ORM models."""

from __future__ import annotations

from core.orm import Model, fields


class MemoPrompt(Model):
    """Reusable prompt template for scheduled memos."""

    _schema = "app"
    _name = "memo_prompts"

    user_id = fields.BigInteger(required=True)
    platform = fields.Text(required=True)
    title = fields.Text(required=True)
    content = fields.Text(required=True)
    created_at = fields.DateTime(auto_now_add=True)
    updated_at = fields.DateTime(auto_now_add=True, auto_now=True)


class ScheduledMemo(Model):
    """Scheduled memo referencing a prompt."""

    _schema = "app"
    _name = "scheduled_memos"

    user_id = fields.BigInteger(required=True)
    platform = fields.Text(required=True)
    prompt_id = fields.ForeignKey(MemoPrompt, on_delete="CASCADE")
    schedule_type = fields.Text(required=True)
    cron = fields.Text()
    run_at = fields.Text()
    enabled = fields.Boolean(default=True)
    created_at = fields.DateTime(auto_now_add=True)
    last_run = fields.DateTime()
