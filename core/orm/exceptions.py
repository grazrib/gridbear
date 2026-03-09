"""ORM exceptions."""


class RecordNotFoundError(ValueError):
    """Raised by get(raise_if_missing=True) when no record matches."""


class MultipleRecordsError(ValueError):
    """Raised by get() when more than one record matches."""


class ValidationError(ValueError):
    """Raised on invalid field name, type mismatch, or missing required value."""


class TenantContextError(RuntimeError):
    """No tenant context set on a tenant-aware model operation."""


class TenantAccessError(PermissionError):
    """Write/delete attempted on a record belonging to another tenant."""


class TenantSafetyError(RuntimeError):
    """Raw query on tenant-aware model without _bypass_tenant or company_id in query."""


# Re-export psycopg IntegrityError (lazy to avoid import failures outside Docker)
try:
    from psycopg.errors import UniqueViolation as IntegrityError  # noqa: F401
except ImportError:

    class IntegrityError(Exception):  # type: ignore[no-redef]
        """Fallback when psycopg is not installed."""
