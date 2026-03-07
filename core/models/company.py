"""Company model — top-level tenant entity for multi-tenancy."""

from core.orm import fields
from core.orm.model import Model


class Company(Model):
    _schema = "app"
    _name = "companies"
    _tenant_field = None  # Company itself is not tenant-scoped

    name = fields.Text(required=True, unique=True)
    slug = fields.Text(required=True, unique=True)
    active = fields.Boolean(default=True)
    logo = fields.Text()
    locale = fields.Text(default="en")
    timezone = fields.Text(default="UTC")
    max_agents = fields.Integer(default=0)
    max_users = fields.Integer(default=0)
    plan = fields.Text(default="free")
    settings = fields.Json(default={})
    created_at = fields.DateTime(auto_now_add=True)
    updated_at = fields.DateTime(auto_now=True)
