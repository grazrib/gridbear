"""CompanyUser model — maps users to companies with roles."""

from core.orm import fields
from core.orm.model import Model

from .company import Company
from .user import User


class CompanyUser(Model):
    _schema = "app"
    _name = "company_users"
    _tenant_field = None  # Junction table, not tenant-scoped itself

    company_id = fields.ForeignKey(Company, on_delete="CASCADE", required=True)
    user_id = fields.ForeignKey(User, on_delete="CASCADE", required=True)
    role = fields.Text(default="member")
    is_default = fields.Boolean(default=False)
    created_at = fields.DateTime(auto_now_add=True)

    _constraints = [
        ("uq_company_user", 'UNIQUE ("company_id", "user_id")'),
    ]
