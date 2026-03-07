"""CompanyUser model — maps users to companies with roles."""

from core.orm import fields
from core.orm.model import Model

from .company import Company


class CompanyUser(Model):
    _schema = "app"
    _name = "company_users"
    _tenant_field = None  # Junction table, not tenant-scoped itself

    company_id = fields.ForeignKey(Company, on_delete="CASCADE", required=True)
    user_id = fields.Integer(required=True)
    role = fields.Text(default="member")
    is_default = fields.Boolean(default=False)
    created_at = fields.DateTime(auto_now_add=True)

    _constraints = [
        ("uq_company_user", 'UNIQUE ("company_id", "user_id")'),
        (
            "fk_company_user_user_id",
            'FOREIGN KEY ("user_id") REFERENCES "app"."users"(id) ON DELETE CASCADE',
        ),
    ]
