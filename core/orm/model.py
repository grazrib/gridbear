"""ORM Model base class — declarative CRUD over PostgreSQL.

Each Model subclass maps to a single table within a PostgreSQL schema.
The ``id`` primary key column is created automatically.

Example::

    class UserInstance(Model):
        _schema = "myplugin"
        _name = "user_instance"

        unified_id = fields.Text(required=True)
        instance_name = fields.Text(required=True, unique=True)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from core.orm.exceptions import (
    MultipleRecordsError,
    RecordNotFoundError,
    TenantAccessError,
    TenantContextError,
    TenantSafetyError,
    ValidationError,
)
from core.orm.fields import DateTime, Field, ForeignKey, TsVector
from core.orm.query import domain_to_sql, kwargs_to_domain, parse_order

_logger = logging.getLogger(__name__)

# Global reference set by Registry.initialize()
_db = None


def set_database(db) -> None:
    """Called by the ORM registry at boot to inject the DatabaseManager."""
    global _db
    _db = db


def get_database():
    if _db is None:
        raise RuntimeError("ORM not initialized — call Registry.initialize() first")
    return _db


@asynccontextmanager
async def transaction():
    """Async context manager for explicit transactions.

    Usage::

        async with transaction() as tx:
            await MyModel.create(field="val", _tx=tx)
            await OtherModel.create(ref=..., _tx=tx)
        # auto-commit on exit, auto-rollback on exception
    """
    db = get_database()
    async with db.acquire() as conn:
        try:
            yield conn
            await conn.execute("COMMIT")
        except BaseException:
            await conn.execute("ROLLBACK")
            raise


class ModelMeta(type):
    """Metaclass that collects Field descriptors and registers the model."""

    _all_models: list[type[Model]] = []

    def __new__(mcs, name, bases, namespace):
        cls = super().__new__(mcs, name, bases, namespace)

        # Skip the abstract Model base
        if name == "Model" and not bases:
            return cls

        # Inherit _tenant_field from parent if not declared
        if "_tenant_field" not in namespace:
            for base in bases:
                if hasattr(base, "_tenant_field") and base._tenant_field is not None:
                    cls._tenant_field = base._tenant_field
                    break

        # Collect declared fields
        fields_dict: dict[str, Field] = {}
        for attr_name, attr_value in list(namespace.items()):
            if isinstance(attr_value, Field):
                attr_value.name = attr_name
                fields_dict[attr_name] = attr_value

        # Auto-inject tenant FK if _tenant_field is set and not already declared
        tenant_field = getattr(cls, "_tenant_field", None)
        if tenant_field and tenant_field not in fields_dict:
            fk = ForeignKey(
                "app.companies", on_delete="RESTRICT", required=True, index=True
            )
            fk.name = tenant_field
            fields_dict[tenant_field] = fk
            setattr(cls, tenant_field, fk)

        cls._fields = fields_dict
        cls._field_names = set(fields_dict.keys())
        cls._table_name = getattr(cls, "_name", name.lower())

        # Register for discovery
        if hasattr(cls, "_schema") and hasattr(cls, "_name"):
            ModelMeta._all_models.append(cls)

        return cls


class Model(metaclass=ModelMeta):
    """Base class for ORM models.

    Subclass attributes:
        _schema (str): PostgreSQL schema name.
        _name (str): Table name (without schema prefix).
        _constraints (list): Optional ``[("name", "SQL")]`` table constraints.
        _indexes (list): Optional ``[("name", "column", "method")]`` indexes.
        _dataclass (type): Optional dataclass for row deserialization.
    """

    _schema: str = ""
    _name: str = ""
    _fields: dict[str, Field] = {}
    _field_names: set[str] = set()
    _table_name: str = ""
    _constraints: list[tuple[str, str]] = []
    _indexes: list[tuple[str, str, str]] = []
    _dataclass: type | None = None
    _primary_key: str = "id"
    _tenant_field: str | None = None

    @classmethod
    def _fq_table(cls) -> str:
        """Fully qualified table name: "schema"."table"."""
        return f'"{cls._schema}"."{cls._table_name}"'

    @classmethod
    def _valid_field_names(cls) -> set[str]:
        """Field names valid for queries (includes primary key)."""
        return cls._field_names | {cls._primary_key}

    @classmethod
    def _validate_kwargs(cls, kwargs: dict, *, allow_pk: bool = False) -> None:
        """Validate that kwargs only reference declared fields."""
        valid = cls._field_names if not allow_pk else cls._valid_field_names()
        invalid = set(kwargs.keys()) - valid
        if invalid:
            raise ValidationError(
                f"Unknown fields for {cls._name}: {sorted(invalid)}. "
                f"Valid: {sorted(valid)}"
            )

    @classmethod
    def _row_to_result(cls, row: dict) -> dict | Any:
        """Convert a raw dict row to the appropriate return type."""
        if row is None:
            return None

        # Apply sql_to_python conversions
        result = dict(row)
        for fname, field in cls._fields.items():
            if fname in result:
                result[fname] = field.sql_to_python(result[fname])

        # Dataclass bridge
        if cls._dataclass is not None:
            import dataclasses

            dc_fields = {f.name for f in dataclasses.fields(cls._dataclass)}
            dc_kwargs = {k: v for k, v in result.items() if k in dc_fields}
            return cls._dataclass(**dc_kwargs)

        return result

    # ── CRUD: async ──────────────────────────────────────────────

    @classmethod
    async def create(cls, *, _tx=None, **values) -> dict:
        """Insert a new record. Returns the created row as dict (always dict, even with _dataclass)."""
        cls._validate_kwargs(values)
        cls._inject_tenant_on_create(values)

        # Apply python_to_sql conversions
        sql_values = {}
        for k, v in values.items():
            field = cls._fields.get(k)
            if field and not isinstance(field, TsVector):
                sql_values[k] = field.python_to_sql(v)
            elif field is None:
                sql_values[k] = v

        # Inject auto_now_add defaults handled in DDL (NOW()), skip in values
        # auto_now fields are not set at create time (only at write)

        if not sql_values:
            # No explicit values — insert default row
            query = f"INSERT INTO {cls._fq_table()} DEFAULT VALUES RETURNING *"
            params: tuple = ()
        else:
            columns = ", ".join(f'"{c}"' for c in sql_values)
            placeholders = ", ".join(["%s"] * len(sql_values))
            query = (
                f"INSERT INTO {cls._fq_table()} ({columns}) "
                f"VALUES ({placeholders}) RETURNING *"
            )
            params = tuple(sql_values.values())

        row = await cls._execute_one(query, params, _tx)
        return dict(row) if row else {}

    @classmethod
    async def get(
        cls,
        *,
        raise_if_missing: bool = False,
        _tx=None,
        **kwargs,
    ) -> dict | Any | None:
        """Fetch a single record by field values.

        Returns dict (or dataclass if _dataclass set), None if not found.
        Raises MultipleRecordsError if more than one result.
        Raises RecordNotFoundError if raise_if_missing=True and not found.
        """
        cls._validate_kwargs(kwargs, allow_pk=True)
        domain = kwargs_to_domain(kwargs)
        where, params = domain_to_sql(domain, cls)

        query = f"SELECT * FROM {cls._fq_table()} WHERE {where}"
        rows = await cls._execute_all(query, tuple(params), _tx)

        if len(rows) > 1:
            raise MultipleRecordsError(
                f"{cls._name}.get() returned {len(rows)} records for {kwargs}"
            )
        if not rows:
            if raise_if_missing:
                raise RecordNotFoundError(
                    f"{cls._name}.get() found no record for {kwargs}"
                )
            return None

        return cls._row_to_result(rows[0])

    @classmethod
    async def search(
        cls,
        domain: list | None = None,
        *,
        order: str = "",
        limit: int = 0,
        offset: int = 0,
        _tx=None,
    ) -> list[dict | Any]:
        """Search records by domain expression.

        Returns list of dicts (or dataclasses if _dataclass set).
        """
        where, params = domain_to_sql(domain or [], cls)
        order_sql = parse_order(order, cls._valid_field_names()) if order else ""

        query = f"SELECT * FROM {cls._fq_table()} WHERE {where} {order_sql}"
        if limit:
            query += f" LIMIT {int(limit)}"
        if offset:
            query += f" OFFSET {int(offset)}"

        rows = await cls._execute_all(query, tuple(params), _tx)
        return [cls._row_to_result(r) for r in rows]

    @classmethod
    async def write(cls, record_id, *, _tx=None, **values) -> int:
        """Update a single record by primary key. Returns number of rows updated."""
        cls._validate_kwargs(values)

        set_parts, params = cls._build_set_clause(values)
        if not set_parts:
            return 0

        pk = cls._primary_key
        query = f'UPDATE {cls._fq_table()} SET {", ".join(set_parts)} WHERE "{pk}" = %s'
        params.append(record_id)
        tenant_sql, tenant_params = cls._tenant_where_clause()
        if tenant_sql:
            query += f" AND {tenant_sql}"
            params.extend(tenant_params)
        rowcount = await cls._execute_rowcount(query, tuple(params), _tx)
        if rowcount == 0 and tenant_sql:
            await cls._check_tenant_access(record_id, _tx)
        return rowcount

    @classmethod
    async def write_multi(cls, domain: list, *, _tx=None, **values) -> int:
        """Update records matching domain. Returns number of rows updated."""
        cls._validate_kwargs(values)

        set_parts, set_params = cls._build_set_clause(values)
        if not set_parts:
            return 0

        where, where_params = domain_to_sql(domain, cls)
        query = f"UPDATE {cls._fq_table()} SET {', '.join(set_parts)} WHERE {where}"
        return await cls._execute_rowcount(query, tuple(set_params + where_params), _tx)

    @classmethod
    async def delete(cls, record_id, *, _tx=None) -> int:
        """Delete a single record by primary key. Returns rows deleted."""
        pk = cls._primary_key
        query = f'DELETE FROM {cls._fq_table()} WHERE "{pk}" = %s'
        params: list = [record_id]
        tenant_sql, tenant_params = cls._tenant_where_clause()
        if tenant_sql:
            query += f" AND {tenant_sql}"
            params.extend(tenant_params)
        rowcount = await cls._execute_rowcount(query, tuple(params), _tx)
        if rowcount == 0 and tenant_sql:
            await cls._check_tenant_access(record_id, _tx)
        return rowcount

    @classmethod
    async def delete_multi(cls, domain: list, *, _tx=None) -> int:
        """Delete records matching domain. Returns number of rows deleted."""
        where, params = domain_to_sql(domain, cls)
        query = f"DELETE FROM {cls._fq_table()} WHERE {where}"
        return await cls._execute_rowcount(query, tuple(params), _tx)

    @classmethod
    async def exists(cls, domain: list | None = None, *, _tx=None, **kwargs) -> bool:
        """Check if at least one record exists. Accepts domain or kwargs."""
        if kwargs:
            domain = kwargs_to_domain(kwargs)
        where, params = domain_to_sql(domain or [], cls)
        query = f"SELECT 1 FROM {cls._fq_table()} WHERE {where} LIMIT 1"
        rows = await cls._execute_all(query, tuple(params), _tx)
        return len(rows) > 0

    @classmethod
    async def count(cls, domain: list | None = None, *, _tx=None, **kwargs) -> int:
        """Count records. Accepts domain or kwargs."""
        if kwargs:
            domain = kwargs_to_domain(kwargs)
        where, params = domain_to_sql(domain or [], cls)
        query = f"SELECT COUNT(*) as cnt FROM {cls._fq_table()} WHERE {where}"
        rows = await cls._execute_all(query, tuple(params), _tx)
        return rows[0]["cnt"] if rows else 0

    @classmethod
    async def raw_search(
        cls,
        query: str,
        params: tuple = (),
        *,
        _tx=None,
        _bypass_tenant: bool = False,
    ) -> list[dict]:
        """Execute raw SQL with {table} placeholder. Returns list of dicts."""
        cls._check_raw_tenant_safety(query, _bypass_tenant)
        query = query.replace("{table}", cls._fq_table())
        return await cls._execute_all(query, params, _tx)

    @classmethod
    async def raw_execute(
        cls,
        query: str,
        params: tuple = (),
        *,
        _tx=None,
        _bypass_tenant: bool = False,
    ) -> int:
        """Execute raw DML with {table} placeholder. Returns rowcount."""
        cls._check_raw_tenant_safety(query, _bypass_tenant)
        query = query.replace("{table}", cls._fq_table())
        return await cls._execute_rowcount(query, params, _tx)

    @classmethod
    async def create_or_update(
        cls,
        *,
        _conflict_fields: tuple[str, ...] | None = None,
        _update_fields: list[str] | None = None,
        _tx=None,
        **values,
    ) -> dict:
        """Upsert: INSERT ... ON CONFLICT DO UPDATE.

        Args:
            _conflict_fields: Columns for ON CONFLICT clause.
                              Defaults to (cls._primary_key,).
            _update_fields: Columns to SET on conflict.
                            Defaults to all provided fields minus conflict
                            fields and auto_now_add-only DateTime fields.
            **values: Column values for the INSERT.

        Returns the upserted row as dict.
        """
        cls._validate_kwargs(values, allow_pk=True)
        cls._inject_tenant_on_create(values)

        if _conflict_fields is None:
            _conflict_fields = (cls._primary_key,)

        # Auto-add tenant field to conflict fields for tenant-aware models
        tenant_field = cls._tenant_field
        if tenant_field and tenant_field not in _conflict_fields:
            _conflict_fields = (tenant_field,) + _conflict_fields

        # Apply python_to_sql conversions
        sql_values: dict = {}
        for k, v in values.items():
            field = cls._fields.get(k)
            if field and not isinstance(field, TsVector):
                sql_values[k] = field.python_to_sql(v)
            else:
                sql_values[k] = v

        # Determine update fields
        if _update_fields is None:
            # Auto: all provided minus conflict fields minus auto_now_add-only
            exclude = set(_conflict_fields)
            for fname, field in cls._fields.items():
                if (
                    isinstance(field, DateTime)
                    and field.auto_now_add
                    and not field.auto_now
                ):
                    exclude.add(fname)
            _update_fields = [f for f in sql_values if f not in exclude]

        # Build INSERT
        columns = ", ".join(f'"{c}"' for c in sql_values)
        placeholders = ", ".join(["%s"] * len(sql_values))
        conflict_cols = ", ".join(f'"{c}"' for c in _conflict_fields)

        # Build DO UPDATE SET
        set_parts: list[str] = []
        for col in _update_fields:
            set_parts.append(f'"{col}" = EXCLUDED."{col}"')

        # Inject auto_now fields
        for fname, field in cls._fields.items():
            if (
                isinstance(field, DateTime)
                and field.auto_now
                and fname not in _update_fields
            ):
                set_parts.append(f'"{fname}" = NOW()')

        if set_parts:
            do_clause = f"DO UPDATE SET {', '.join(set_parts)}"
        else:
            do_clause = "DO NOTHING"

        query = (
            f"INSERT INTO {cls._fq_table()} ({columns}) "
            f"VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict_cols}) {do_clause} "
            f"RETURNING *"
        )
        params = tuple(sql_values.values())
        row = await cls._execute_one(query, params, _tx)
        return dict(row) if row else {}

    # ── CRUD: sync variants ──────────────────────────────────────

    @classmethod
    def create_sync(cls, **values) -> dict:
        """Synchronous create."""
        cls._validate_kwargs(values)
        cls._inject_tenant_on_create(values)

        sql_values = {}
        for k, v in values.items():
            field = cls._fields.get(k)
            if field and not isinstance(field, TsVector):
                sql_values[k] = field.python_to_sql(v)
            elif field is None:
                sql_values[k] = v

        if not sql_values:
            query = f"INSERT INTO {cls._fq_table()} DEFAULT VALUES RETURNING *"
            params: tuple = ()
        else:
            columns = ", ".join(f'"{c}"' for c in sql_values)
            placeholders = ", ".join(["%s"] * len(sql_values))
            query = (
                f"INSERT INTO {cls._fq_table()} ({columns}) "
                f"VALUES ({placeholders}) RETURNING *"
            )
            params = tuple(sql_values.values())

        db = get_database()
        with db.acquire_sync() as conn:
            row = conn.execute(query, params).fetchone()
            conn.commit()
            return dict(row) if row else {}

    @classmethod
    def get_sync(cls, *, raise_if_missing: bool = False, **kwargs) -> dict | Any | None:
        """Synchronous get."""
        cls._validate_kwargs(kwargs, allow_pk=True)
        domain = kwargs_to_domain(kwargs)
        where, params = domain_to_sql(domain, cls)

        query = f"SELECT * FROM {cls._fq_table()} WHERE {where}"

        db = get_database()
        with db.acquire_sync() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()

        if len(rows) > 1:
            raise MultipleRecordsError(
                f"{cls._name}.get_sync() returned {len(rows)} records for {kwargs}"
            )
        if not rows:
            if raise_if_missing:
                raise RecordNotFoundError(
                    f"{cls._name}.get_sync() found no record for {kwargs}"
                )
            return None

        return cls._row_to_result(dict(rows[0]))

    @classmethod
    def search_sync(
        cls,
        domain: list | None = None,
        *,
        order: str = "",
        limit: int = 0,
        offset: int = 0,
    ) -> list[dict | Any]:
        """Synchronous search."""
        where, params = domain_to_sql(domain or [], cls)
        order_sql = parse_order(order, cls._valid_field_names()) if order else ""

        query = f"SELECT * FROM {cls._fq_table()} WHERE {where} {order_sql}"
        if limit:
            query += f" LIMIT {int(limit)}"
        if offset:
            query += f" OFFSET {int(offset)}"

        db = get_database()
        with db.acquire_sync() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()

        return [cls._row_to_result(dict(r)) for r in rows]

    @classmethod
    def write_sync(cls, record_id, **values) -> int:
        """Synchronous write."""
        cls._validate_kwargs(values)

        set_parts, params = cls._build_set_clause(values)
        if not set_parts:
            return 0

        pk = cls._primary_key
        query = f'UPDATE {cls._fq_table()} SET {", ".join(set_parts)} WHERE "{pk}" = %s'
        params.append(record_id)
        tenant_sql, tenant_params = cls._tenant_where_clause()
        if tenant_sql:
            query += f" AND {tenant_sql}"
            params.extend(tenant_params)

        db = get_database()
        with db.acquire_sync() as conn:
            result = conn.execute(query, tuple(params))
            conn.commit()
            rowcount = result.rowcount
        if rowcount == 0 and tenant_sql:
            cls._check_tenant_access_sync(record_id)
        return rowcount

    @classmethod
    def delete_sync(cls, record_id) -> int:
        """Synchronous delete."""
        pk = cls._primary_key
        query = f'DELETE FROM {cls._fq_table()} WHERE "{pk}" = %s'
        params: list = [record_id]
        tenant_sql, tenant_params = cls._tenant_where_clause()
        if tenant_sql:
            query += f" AND {tenant_sql}"
            params.extend(tenant_params)
        db = get_database()
        with db.acquire_sync() as conn:
            result = conn.execute(query, tuple(params))
            conn.commit()
            rowcount = result.rowcount
        if rowcount == 0 and tenant_sql:
            cls._check_tenant_access_sync(record_id)
        return rowcount

    @classmethod
    def write_multi_sync(cls, domain: list, **values) -> int:
        """Synchronous write_multi."""
        cls._validate_kwargs(values)
        set_parts, set_params = cls._build_set_clause(values)
        if not set_parts:
            return 0
        where, where_params = domain_to_sql(domain, cls)
        query = f"UPDATE {cls._fq_table()} SET {', '.join(set_parts)} WHERE {where}"
        db = get_database()
        with db.acquire_sync() as conn:
            result = conn.execute(query, tuple(set_params + where_params))
            conn.commit()
            return result.rowcount

    @classmethod
    def delete_multi_sync(cls, domain: list) -> int:
        """Synchronous unlink_multi."""
        where, params = domain_to_sql(domain, cls)
        query = f"DELETE FROM {cls._fq_table()} WHERE {where}"
        db = get_database()
        with db.acquire_sync() as conn:
            result = conn.execute(query, tuple(params))
            conn.commit()
            return result.rowcount

    @classmethod
    def count_sync(cls, domain: list | None = None, **kwargs) -> int:
        """Synchronous count."""
        if kwargs:
            domain = kwargs_to_domain(kwargs)
        where, params = domain_to_sql(domain or [], cls)
        query = f"SELECT COUNT(*) as cnt FROM {cls._fq_table()} WHERE {where}"
        db = get_database()
        with db.acquire_sync() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return rows[0]["cnt"] if rows else 0

    @classmethod
    def exists_sync(cls, domain: list | None = None, **kwargs) -> bool:
        """Synchronous exists."""
        if kwargs:
            domain = kwargs_to_domain(kwargs)
        where, params = domain_to_sql(domain or [], cls)
        query = f"SELECT 1 FROM {cls._fq_table()} WHERE {where} LIMIT 1"
        db = get_database()
        with db.acquire_sync() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return len(rows) > 0

    @classmethod
    def raw_search_sync(
        cls, query: str, params: tuple = (), *, _bypass_tenant: bool = False
    ) -> list[dict]:
        """Synchronous raw_search with {table} placeholder."""
        cls._check_raw_tenant_safety(query, _bypass_tenant)
        query = query.replace("{table}", cls._fq_table())
        db = get_database()
        with db.acquire_sync() as conn:
            return conn.execute(query, params).fetchall()

    @classmethod
    def raw_execute_sync(
        cls, query: str, params: tuple = (), *, _bypass_tenant: bool = False
    ) -> int:
        """Synchronous raw_execute with {table} placeholder."""
        cls._check_raw_tenant_safety(query, _bypass_tenant)
        query = query.replace("{table}", cls._fq_table())
        db = get_database()
        with db.acquire_sync() as conn:
            result = conn.execute(query, params)
            conn.commit()
            return result.rowcount

    @classmethod
    def create_or_update_sync(
        cls,
        *,
        _conflict_fields: tuple[str, ...] | None = None,
        _update_fields: list[str] | None = None,
        **values,
    ) -> dict:
        """Synchronous upsert."""
        cls._validate_kwargs(values, allow_pk=True)
        cls._inject_tenant_on_create(values)

        if _conflict_fields is None:
            _conflict_fields = (cls._primary_key,)

        # Auto-add tenant field to conflict fields for tenant-aware models
        tenant_field = cls._tenant_field
        if tenant_field and tenant_field not in _conflict_fields:
            _conflict_fields = (tenant_field,) + _conflict_fields

        sql_values: dict = {}
        for k, v in values.items():
            field = cls._fields.get(k)
            if field and not isinstance(field, TsVector):
                sql_values[k] = field.python_to_sql(v)
            else:
                sql_values[k] = v

        if _update_fields is None:
            exclude = set(_conflict_fields)
            for fname, field in cls._fields.items():
                if (
                    isinstance(field, DateTime)
                    and field.auto_now_add
                    and not field.auto_now
                ):
                    exclude.add(fname)
            _update_fields = [f for f in sql_values if f not in exclude]

        columns = ", ".join(f'"{c}"' for c in sql_values)
        placeholders = ", ".join(["%s"] * len(sql_values))
        conflict_cols = ", ".join(f'"{c}"' for c in _conflict_fields)

        set_parts: list[str] = []
        for col in _update_fields:
            set_parts.append(f'"{col}" = EXCLUDED."{col}"')

        for fname, field in cls._fields.items():
            if (
                isinstance(field, DateTime)
                and field.auto_now
                and fname not in _update_fields
            ):
                set_parts.append(f'"{fname}" = NOW()')

        if set_parts:
            do_clause = f"DO UPDATE SET {', '.join(set_parts)}"
        else:
            do_clause = "DO NOTHING"

        query = (
            f"INSERT INTO {cls._fq_table()} ({columns}) "
            f"VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict_cols}) {do_clause} "
            f"RETURNING *"
        )
        params = tuple(sql_values.values())

        db = get_database()
        with db.acquire_sync() as conn:
            row = conn.execute(query, params).fetchone()
            conn.commit()
            return dict(row) if row else {}

    # ── Internal helpers ─────────────────────────────────────────

    @classmethod
    def _build_set_clause(cls, values: dict) -> tuple[list[str], list]:
        """Build SET clause parts and params for UPDATE.

        Injects auto_now fields automatically.
        """
        sql_values = {}
        for k, v in values.items():
            field = cls._fields.get(k)
            if field and not isinstance(field, TsVector):
                sql_values[k] = field.python_to_sql(v)
            elif field is None:
                sql_values[k] = v

        set_parts = []
        params = []
        for col, val in sql_values.items():
            set_parts.append(f'"{col}" = %s')
            params.append(val)

        # Inject auto_now fields
        for fname, field in cls._fields.items():
            if isinstance(field, DateTime) and field.auto_now and fname not in values:
                set_parts.append(f'"{fname}" = NOW()')

        return set_parts, params

    # ── Tenant helpers ───────────────────────────────────────────

    @classmethod
    def _inject_tenant_on_create(cls, values: dict) -> None:
        """Inject tenant company_id into create values if model is tenant-aware."""
        tenant_field = cls._tenant_field
        if not tenant_field:
            return
        if tenant_field in values:
            return  # explicitly provided

        from core.tenant import SUPERADMIN_BYPASS, get_tenant

        tenant_id = get_tenant()
        if tenant_id is None:
            raise TenantContextError(
                f"No tenant context set for tenant-aware model "
                f"{cls._schema}.{cls._name}. Call set_tenant() before creating."
            )
        if tenant_id == SUPERADMIN_BYPASS:
            raise TenantContextError(
                f"SUPERADMIN_BYPASS cannot auto-inject {tenant_field} on create. "
                f"Provide {tenant_field} explicitly."
            )
        values[tenant_field] = tenant_id

    @classmethod
    def _tenant_where_clause(cls) -> tuple[str, list]:
        """Return (sql_fragment, params) for tenant filtering on write/delete.

        Returns ("", []) if model is not tenant-aware or bypass is active.
        """
        tenant_field = cls._tenant_field
        if not tenant_field:
            return "", []

        from core.tenant import SUPERADMIN_BYPASS, get_tenant

        tenant_id = get_tenant()
        if tenant_id is None:
            raise TenantContextError(
                f"No tenant context set for tenant-aware model "
                f"{cls._schema}.{cls._name}. Call set_tenant() before writing."
            )
        if tenant_id == SUPERADMIN_BYPASS:
            return "", []
        return f'"{tenant_field}" = %s', [tenant_id]

    @classmethod
    async def _check_tenant_access(cls, record_id, tx=None) -> None:
        """After a write/delete returns 0 rows, check if record exists in another tenant."""
        pk = cls._primary_key
        query = f'SELECT 1 FROM {cls._fq_table()} WHERE "{pk}" = %s LIMIT 1'
        rows = await cls._execute_all(query, (record_id,), tx)
        if rows:
            raise TenantAccessError(
                f"Record {cls._schema}.{cls._name}(id={record_id}) "
                f"belongs to another tenant."
            )

    @classmethod
    def _check_tenant_access_sync(cls, record_id) -> None:
        """Sync variant of _check_tenant_access."""
        pk = cls._primary_key
        query = f'SELECT 1 FROM {cls._fq_table()} WHERE "{pk}" = %s LIMIT 1'
        db = get_database()
        with db.acquire_sync() as conn:
            rows = conn.execute(query, (record_id,)).fetchall()
        if rows:
            raise TenantAccessError(
                f"Record {cls._schema}.{cls._name}(id={record_id}) "
                f"belongs to another tenant."
            )

    @classmethod
    def _check_raw_tenant_safety(cls, query: str, bypass: bool) -> None:
        """Raise TenantSafetyError if raw query on tenant-aware model lacks safety."""
        tenant_field = cls._tenant_field
        if not tenant_field:
            return
        if bypass:
            _logger.warning(
                "Raw query on %s.%s with _bypass_tenant=True",
                cls._schema,
                cls._name,
            )
            return
        if tenant_field not in query:
            raise TenantSafetyError(
                f"Raw query on tenant-aware model {cls._schema}.{cls._name} "
                f"must include '{tenant_field}' in the query or use "
                f"_bypass_tenant=True."
            )

    @classmethod
    async def _execute_one(cls, query: str, params: tuple, tx=None) -> dict | None:
        if tx is not None:
            cur = await tx.execute(query, params)
            return await cur.fetchone()

        db = get_database()
        async with db.acquire() as conn:
            cur = await conn.execute(query, params)
            row = await cur.fetchone()
            await conn.execute("COMMIT")
            return row

    @classmethod
    async def _execute_all(cls, query: str, params: tuple, tx=None) -> list[dict]:
        if tx is not None:
            cur = await tx.execute(query, params)
            return await cur.fetchall()

        db = get_database()
        async with db.acquire() as conn:
            cur = await conn.execute(query, params)
            return await cur.fetchall()

    @classmethod
    async def _execute_rowcount(cls, query: str, params: tuple, tx=None) -> int:
        if tx is not None:
            cur = await tx.execute(query, params)
            return cur.rowcount

        db = get_database()
        async with db.acquire() as conn:
            cur = await conn.execute(query, params)
            await conn.execute("COMMIT")
            return cur.rowcount
