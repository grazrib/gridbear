"""ORM models for the memory plugin — pgvector-backed episodic + declarative memory."""

from core.orm import Model, fields


class EpisodicMemory(Model):
    """Conversation turn memories — stores user+assistant interaction embeddings."""

    _schema = "memory"
    _name = "episodic"
    _primary_key = "id"

    id = fields.Text(required=True)
    user_id = fields.Text(required=True, index=True)
    platform = fields.Text()
    document = fields.Encrypted(required=True)
    embedding = fields.Vector(384)
    memory_type = fields.Text(default="episodic")
    user_message_preview = fields.Encrypted()
    metadata = fields.Json()
    created_at = fields.DateTime(auto_now_add=True)


class DeclarativeMemory(Model):
    """Extracted facts and knowledge — stores per-fact embeddings."""

    _schema = "memory"
    _name = "declarative"
    _primary_key = "id"

    id = fields.Text(required=True)
    user_id = fields.Text(required=True, index=True)
    document = fields.Encrypted(required=True)
    embedding = fields.Vector(384)
    memory_type = fields.Text(default="declarative")
    metadata = fields.Json()
    created_at = fields.DateTime(auto_now_add=True)
