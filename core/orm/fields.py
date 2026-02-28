"""ORM field descriptors — declarative column definitions mapped to PostgreSQL types."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.orm.model import Model


class Field:
    """Base field descriptor."""

    pg_type: str = ""

    def __init__(
        self,
        *,
        required: bool = False,
        default: Any = None,
        unique: bool = False,
        index: bool = False,
    ):
        self.required = required
        self.default = default
        self.unique = unique
        self.index = index
        # Set by metaclass
        self.name: str = ""

    def ddl_column(self) -> str:
        """Generate the column DDL fragment (without column name)."""
        parts = [self.pg_type]
        if self.required:
            parts.append("NOT NULL")
        if self.unique:
            parts.append("UNIQUE")
        default = self._ddl_default()
        if default is not None:
            parts.append(f"DEFAULT {default}")
        return " ".join(parts)

    def _ddl_default(self) -> str | None:
        """Return SQL DEFAULT expression, or None."""
        if self.default is None:
            return None
        if isinstance(self.default, bool):
            return "TRUE" if self.default else "FALSE"
        if isinstance(self.default, (int, float)):
            return str(self.default)
        if isinstance(self.default, str):
            escaped = self.default.replace("'", "''")
            return f"'{escaped}'"
        # Callable defaults are handled in Python, not in DDL
        return None

    def python_to_sql(self, value: Any) -> Any:
        """Convert a Python value to SQL-compatible value. Override for custom types."""
        return value

    def sql_to_python(self, value: Any) -> Any:
        """Convert a SQL result value to Python. Override for custom types."""
        return value


# --- Concrete field types ---


class Serial(Field):
    """Auto-incrementing integer (SERIAL). Used internally for the id PK."""

    pg_type = "SERIAL"


class Integer(Field):
    pg_type = "INTEGER"


class BigInteger(Field):
    pg_type = "BIGINT"


class Text(Field):
    def __init__(self, *, max_length: int | None = None, **kwargs):
        super().__init__(**kwargs)
        self.max_length = max_length

    @property
    def pg_type(self) -> str:
        if self.max_length:
            return f"VARCHAR({self.max_length})"
        return "TEXT"

    def ddl_column(self) -> str:
        parts = [self.pg_type]
        if self.required:
            parts.append("NOT NULL")
        if self.unique:
            parts.append("UNIQUE")
        default = self._ddl_default()
        if default is not None:
            parts.append(f"DEFAULT {default}")
        return " ".join(parts)


class Boolean(Field):
    pg_type = "BOOLEAN"


class Float(Field):
    pg_type = "DOUBLE PRECISION"


class Numeric(Field):
    def __init__(self, precision: int = 10, scale: int = 2, **kwargs):
        super().__init__(**kwargs)
        self.precision = precision
        self.scale = scale

    @property
    def pg_type(self) -> str:
        return f"NUMERIC({self.precision},{self.scale})"

    def ddl_column(self) -> str:
        parts = [self.pg_type]
        if self.required:
            parts.append("NOT NULL")
        if self.unique:
            parts.append("UNIQUE")
        default = self._ddl_default()
        if default is not None:
            parts.append(f"DEFAULT {default}")
        return " ".join(parts)


class DateTime(Field):
    pg_type = "TIMESTAMPTZ"

    def __init__(self, *, auto_now_add: bool = False, auto_now: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.auto_now_add = auto_now_add
        self.auto_now = auto_now

    def _ddl_default(self) -> str | None:
        if self.auto_now_add:
            return "NOW()"
        return super()._ddl_default()


class Date(Field):
    pg_type = "DATE"


class Json(Field):
    """JSONB field with automatic serialization/deserialization."""

    pg_type = "JSONB"

    def _ddl_default(self) -> str | None:
        if self.default is not None:
            import json as _json

            return f"'{_json.dumps(self.default)}'::jsonb"
        return None

    def python_to_sql(self, value: Any) -> Any:
        if value is None:
            return None
        import json as _json

        return _json.dumps(value)

    def sql_to_python(self, value: Any) -> Any:
        # psycopg3 with dict_row auto-deserializes JSONB to Python types
        # (dict, list, str, int, float, bool, None) — no extra conversion needed
        return value


class Vector(Field):
    """pgvector vector column for similarity search."""

    def __init__(self, dimensions: int, **kwargs):
        super().__init__(**kwargs)
        self.dimensions = dimensions

    @property
    def pg_type(self) -> str:
        return f"vector({self.dimensions})"

    def python_to_sql(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        # Convert list/array to pgvector string format: [0.1, 0.2, ...]
        return str(value)

    def sql_to_python(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            # pgvector returns '[0.1,0.2,...]' — parse to list of floats
            return [float(x) for x in value.strip("[]").split(",")]
        return value


class Binary(Field):
    pg_type = "BYTEA"


class ForeignKey(Field):
    """Foreign key reference to another Model."""

    def __init__(
        self,
        target: type[Model] | str,
        *,
        on_delete: str = "CASCADE",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.target = target
        self.on_delete = on_delete.upper()
        if self.on_delete not in ("CASCADE", "SET NULL", "RESTRICT"):
            raise ValueError(f"Invalid on_delete: {self.on_delete}")

    @property
    def pg_type(self) -> str:
        return "INTEGER"

    def ddl_column(self) -> str:
        target_table = self._resolve_target_table()
        parts = [
            self.pg_type,
            f"REFERENCES {target_table}(id)",
            f"ON DELETE {self.on_delete}",
        ]
        if self.required:
            parts.append("NOT NULL")
        if self.unique:
            parts.append("UNIQUE")
        default = self._ddl_default()
        if default is not None:
            parts.append(f"DEFAULT {default}")
        return " ".join(parts)

    def _resolve_target_table(self) -> str:
        if isinstance(self.target, str):
            return self.target
        return f'"{self.target._schema}"."{self.target._table_name}"'


class TsVector(Field):
    """Full-text search vector — GENERATED ALWAYS AS column.

    PostgreSQL maintains this column automatically via the STORED generated column.
    """

    pg_type = "TSVECTOR"

    def __init__(self, *, source: str, config: str = "simple", **kwargs):
        kwargs.setdefault("index", True)
        super().__init__(**kwargs)
        self.source = source
        self.config = config

    def ddl_column(self) -> str:
        return (
            f"TSVECTOR GENERATED ALWAYS AS "
            f"(to_tsvector('{self.config}', COALESCE({self.source}, ''))) STORED"
        )


class Encrypted(Text):
    """Transparent encryption at rest — stores AES-256-GCM ciphertext as TEXT.

    Encrypts on write (python_to_sql) and decrypts on read (sql_to_python).
    Handles pre-migration plaintext gracefully via is_encrypted() check.
    """

    def python_to_sql(self, value):
        if value is None:
            return None
        from core.encryption import encrypt, is_encrypted

        s = str(value)
        return s if is_encrypted(s) else encrypt(s)

    def sql_to_python(self, value):
        if value is None:
            return None
        from core.encryption import decrypt, is_encrypted

        s = str(value)
        return decrypt(s) if is_encrypted(s) else s
