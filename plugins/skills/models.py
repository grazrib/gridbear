"""Skills plugin ORM models."""

from __future__ import annotations

from core.orm import Model, fields


class Skill(Model):
    """Reusable prompt template / context skill."""

    _schema = "app"
    _name = "skills"

    name = fields.Text(required=True, unique=True)
    title = fields.Text(required=True)
    description = fields.Text()
    prompt = fields.Text(required=True)
    category = fields.Text(default="other")
    plugin_name = fields.Text()
    skill_type = fields.Text(default="user")
    created_by = fields.BigInteger()
    created_by_platform = fields.Text()
    shared = fields.Boolean(default=True)
    created_at = fields.DateTime(auto_now_add=True)
    updated_at = fields.DateTime(auto_now_add=True, auto_now=True)
