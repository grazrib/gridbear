"""LiveKit Agent ORM models."""

from __future__ import annotations

from core.orm import Model, fields


class LiveKitSession(Model):
    """Active LiveKit voice call session."""

    _schema = "app"
    _name = "livekit_sessions"
    _primary_key = "room_name"

    room_name = fields.Text(required=True)
    user_id = fields.Text(required=True)
    user_name = fields.Text()
    user_token = fields.Text(required=True)
    agent_token = fields.Text(required=True)
    ws_url = fields.Text(required=True)
    cleanup_token = fields.Text()
    created_at = fields.DateTime(auto_now_add=True)
    ended_at = fields.DateTime()
    end_reason = fields.Text()
