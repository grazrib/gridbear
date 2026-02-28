"""GridBear ORM — lightweight Odoo-inspired ORM over PostgreSQL.

Usage::

    from core.orm import Model, fields, transaction

    class MyModel(Model):
        _schema = "my_plugin"
        _name = "my_table"

        name = fields.Text(required=True)
        active = fields.Boolean(default=True)

    # CRUD
    record = await MyModel.create(name="test")
    found = await MyModel.get(id=record["id"])
    results = await MyModel.search([("active", "=", True)])
    await MyModel.write(record["id"], name="updated")
    await MyModel.delete(record["id"])
"""

from core.orm import fields  # noqa: F401
from core.orm.model import Model, transaction  # noqa: F401
from core.orm.registry import Registry  # noqa: F401
