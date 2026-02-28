"""Value serialization and field filtering for REST API responses."""

import base64
from datetime import date, datetime
from decimal import Decimal


def serialize_value(value):
    """Convert a single value to a JSON-safe representation."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    return value


def serialize_record(record: dict, fields: list[str] | None = None) -> dict:
    """Serialize a full record dict, optionally filtering to specific fields.

    The primary key is always included regardless of the fields filter.
    """
    if fields:
        allowed = set(fields)
        record = {k: v for k, v in record.items() if k in allowed}
    return {k: serialize_value(v) for k, v in record.items()}
