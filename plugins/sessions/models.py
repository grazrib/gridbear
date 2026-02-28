"""Sessions plugin ORM models.

Declarative models for chat session management:
- SessionRecord: user chat sessions with TTL
- SessionMessage: legacy messages linked to sessions
- ChatHistory: persistent cross-session history with encryption at rest
"""

from __future__ import annotations

from core.orm import Model, fields


class SessionRecord(Model):
    """A user chat session with TTL-based expiry."""

    _schema = "chat"
    _name = "sessions"

    user_id = fields.BigInteger(required=True)
    platform = fields.Text(required=True)
    runner_session_id = fields.Text()
    created_at = fields.DateTime(auto_now_add=True)
    updated_at = fields.DateTime(auto_now_add=True, auto_now=True)


class SessionMessage(Model):
    """Legacy message within a session (superseded by ChatHistory)."""

    _schema = "chat"
    _name = "messages"

    session_id = fields.ForeignKey(SessionRecord, on_delete="CASCADE")
    role = fields.Text(required=True)
    content = fields.Text(required=True)
    created_at = fields.DateTime(auto_now_add=True)


class ChatHistory(Model):
    """Persistent cross-session chat history with encryption at rest."""

    _schema = "chat"
    _name = "chat_history"

    user_id = fields.BigInteger(required=True)
    platform = fields.Text(required=True)
    username = fields.Text()
    role = fields.Text(required=True)
    content = fields.Encrypted(required=True)
    created_at = fields.DateTime(auto_now_add=True)
