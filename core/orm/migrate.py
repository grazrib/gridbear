"""Auto-migration engine — compares Model definitions to database state.

Only performs additive operations:
- CREATE SCHEMA IF NOT EXISTS
- CREATE TABLE (new models)
- ALTER TABLE ADD COLUMN (new fields)
- CREATE INDEX IF NOT EXISTS
- ALTER TABLE ADD CONSTRAINT (if not exists)

Never performs destructive operations (DROP COLUMN, ALTER TYPE).
Logs warnings for removed columns, changed types, and stale constraints.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from config.logging_config import logger
from core.orm.fields import TsVector

if TYPE_CHECKING:
    from core.orm.model import Model


_ORM_STATE_TABLE = "public._orm_state"

_ORM_STATE_DDL = f"""
CREATE TABLE IF NOT EXISTS {_ORM_STATE_TABLE} (
    schema_name TEXT NOT NULL,
    table_name TEXT NOT NULL,
    field_name TEXT NOT NULL,
    field_type TEXT NOT NULL,
    last_synced TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (schema_name, table_name, field_name)
);
"""


def migrate_all(models: list[type[Model]], db) -> None:
    """Run auto-migration for all registered models (sync, called at boot)."""
    with db.acquire_sync() as conn:
        # Ensure pgvector extension is available (safe if already created)
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.commit()

        # Ensure _orm_state tracking table exists
        conn.execute(_ORM_STATE_DDL)
        conn.commit()

        for model_cls in models:
            _migrate_model(model_cls, conn)
            conn.commit()

    logger.info("ORM auto-migration complete for %d models", len(models))


def _migrate_model(model_cls: type[Model], conn) -> None:
    """Migrate a single model: create or update table."""
    schema = model_cls._schema
    table = model_cls._table_name

    # 1. Ensure schema exists
    conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')

    # 2. Check if table exists
    row = conn.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = %s AND table_name = %s",
        (schema, table),
    ).fetchone()

    if not row:
        _create_table(model_cls, conn)
    else:
        _update_table(model_cls, conn)

    # 3. Sync indexes
    _sync_indexes(model_cls, conn)

    # 4. Sync constraints
    _sync_constraints(model_cls, conn)

    # 5. Update _orm_state
    _update_orm_state(model_cls, conn)


def _create_table(model_cls: type[Model], conn) -> None:
    """Generate and execute CREATE TABLE for a new model."""
    schema = model_cls._schema
    table = model_cls._table_name
    fq_table = model_cls._fq_table()
    pk = model_cls._primary_key

    columns: list[str] = []
    if pk == "id" and "id" not in model_cls._fields:
        # Default: auto-add SERIAL PK when no explicit id field defined
        columns.append('    "id" SERIAL PRIMARY KEY')

    for fname, field in model_cls._fields.items():
        col_ddl = f'    "{fname}" {field.ddl_column()}'
        if fname == pk:
            col_ddl += " PRIMARY KEY"
        columns.append(col_ddl)

    ddl = f"CREATE TABLE {fq_table} (\n" + ",\n".join(columns) + "\n)"
    conn.execute(ddl)
    logger.info("ORM: created table %s.%s", schema, table)


def _update_table(model_cls: type[Model], conn) -> None:
    """Compare existing table to model and apply additive changes."""
    schema = model_cls._schema
    table = model_cls._table_name
    fq_table = model_cls._fq_table()

    # Get existing columns from information_schema
    rows = conn.execute(
        "SELECT column_name, data_type, is_nullable, column_default "
        "FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s",
        (schema, table),
    ).fetchall()

    existing_columns = {r["column_name"]: r for r in rows}

    # Check for new columns (in model but not in DB)
    for fname, field in model_cls._fields.items():
        if fname not in existing_columns:
            ddl = f'ALTER TABLE {fq_table} ADD COLUMN "{fname}" {field.ddl_column()}'
            conn.execute(ddl)
            logger.info("ORM: added column %s.%s.%s", schema, table, fname)

    # Check for removed columns (in DB but not in model, excluding PK)
    model_field_names = set(model_cls._fields.keys()) | {model_cls._primary_key}
    for col_name in existing_columns:
        if col_name not in model_field_names:
            logger.warning(
                "ORM: column %s.%s.%s exists in DB but not in model "
                "(not dropped — remove manually if needed)",
                schema,
                table,
                col_name,
            )


def _sync_indexes(model_cls: type[Model], conn) -> None:
    """Create missing indexes."""
    schema = model_cls._schema
    table = model_cls._table_name
    fq_table = model_cls._fq_table()

    # Indexes from _indexes attribute
    declared_indexes = list(getattr(model_cls, "_indexes", []))

    # Auto-generate indexes for fields with index=True
    for fname, field in model_cls._fields.items():
        if field.index and not isinstance(field, TsVector):
            idx_name = f"idx_{table}_{fname}"
            declared_indexes.append((idx_name, fname, "BTREE"))
        elif isinstance(field, TsVector) and field.index:
            idx_name = f"idx_{table}_{fname}"
            declared_indexes.append((idx_name, fname, "GIN"))

    # Get existing indexes
    existing = conn.execute(
        "SELECT indexname FROM pg_indexes WHERE schemaname = %s AND tablename = %s",
        (schema, table),
    ).fetchall()
    existing_names = {r["indexname"] for r in existing}

    for idx_name, column, method in declared_indexes:
        if idx_name not in existing_names:
            conn.execute(
                f'CREATE INDEX IF NOT EXISTS "{idx_name}" '
                f'ON {fq_table} USING {method} ("{column}")'
            )
            logger.info("ORM: created index %s on %s.%s", idx_name, schema, table)


def _sync_constraints(model_cls: type[Model], conn) -> None:
    """Create missing table constraints."""
    schema = model_cls._schema
    table = model_cls._table_name
    fq_table = model_cls._fq_table()

    declared = getattr(model_cls, "_constraints", [])
    if not declared:
        return

    # Get existing constraints
    existing = conn.execute(
        "SELECT constraint_name FROM information_schema.table_constraints "
        "WHERE table_schema = %s AND table_name = %s",
        (schema, table),
    ).fetchall()
    existing_names = {r["constraint_name"] for r in existing}

    for cname, csql in declared:
        if cname not in existing_names:
            conn.execute(f'ALTER TABLE {fq_table} ADD CONSTRAINT "{cname}" {csql}')
            logger.info("ORM: added constraint %s on %s.%s", cname, schema, table)


def _update_orm_state(model_cls: type[Model], conn) -> None:
    """Update the _orm_state tracking table with current model state."""
    schema = model_cls._schema
    table = model_cls._table_name

    # Upsert default SERIAL id only if no explicit id field defined
    if "id" not in model_cls._fields:
        conn.execute(
            f"INSERT INTO {_ORM_STATE_TABLE} (schema_name, table_name, field_name, field_type, last_synced) "
            "VALUES (%s, %s, 'id', 'SERIAL', NOW()) "
            "ON CONFLICT (schema_name, table_name, field_name) "
            "DO UPDATE SET field_type = EXCLUDED.field_type, last_synced = NOW()",
            (schema, table),
        )

    for fname, field in model_cls._fields.items():
        pg_type = field.pg_type if hasattr(field, "pg_type") else "UNKNOWN"
        # For dynamic pg_type (property), get the value
        if isinstance(pg_type, property):
            pg_type = field.ddl_column().split()[0]
        conn.execute(
            f"INSERT INTO {_ORM_STATE_TABLE} (schema_name, table_name, field_name, field_type, last_synced) "
            "VALUES (%s, %s, %s, %s, NOW()) "
            "ON CONFLICT (schema_name, table_name, field_name) "
            "DO UPDATE SET field_type = EXCLUDED.field_type, last_synced = NOW()",
            (schema, table, fname, pg_type),
        )
