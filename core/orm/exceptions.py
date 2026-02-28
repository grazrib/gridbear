"""ORM exceptions."""


class RecordNotFoundError(ValueError):
    """Raised by get(raise_if_missing=True) when no record matches."""


class MultipleRecordsError(ValueError):
    """Raised by get() when more than one record matches."""


class ValidationError(ValueError):
    """Raised on invalid field name, type mismatch, or missing required value."""


# Re-export psycopg IntegrityError (lazy to avoid import failures outside Docker)
try:
    from psycopg.errors import UniqueViolation as IntegrityError  # noqa: F401
except ImportError:

    class IntegrityError(Exception):  # type: ignore[no-redef]
        """Fallback when psycopg is not installed."""
