"""Domain expression parser — converts Odoo-style domains to SQL WHERE clauses.

Domain syntax:
    [("field", "=", value)]                          # simple
    ["&", ("f1", "=", v1), ("f2", "=", v2)]         # AND (default implicit)
    ["|", ("f1", "=", v1), ("f2", "=", v2)]         # OR
    ["!", ("f1", "=", v1)]                           # NOT

Multiple top-level tuples are implicitly ANDed:
    [("f1", "=", v1), ("f2", ">", v2)]  →  f1 = %s AND f2 > %s
"""

from __future__ import annotations

from typing import Any

from core.orm.exceptions import ValidationError

_VALID_OPERATORS = frozenset(
    {
        "=",
        "!=",
        ">",
        ">=",
        "<",
        "<=",
        "in",
        "not in",
        "like",
        "ilike",
        "is",
        "is not",
        "@@",
    }
)

_OP_SQL = {
    "=": "=",
    "!=": "!=",
    ">": ">",
    ">=": ">=",
    "<": "<",
    "<=": "<=",
    "like": "LIKE",
    "ilike": "ILIKE",
    "@@": "@@",
}


def domain_to_sql(
    domain: list,
    valid_fields: set[str],
) -> tuple[str, list[Any]]:
    """Parse a domain expression into a SQL WHERE clause.

    Multiple top-level leaves are implicitly ANDed:
        [("a", "=", 1), ("b", "=", 2)]  →  "a" = %s AND "b" = %s

    Args:
        domain: Odoo-style domain list.
        valid_fields: Allowed field names (validated against model).

    Returns:
        (where_clause, params) — clause WITHOUT the "WHERE" keyword.
        Empty domain returns ("TRUE", []).
    """
    if not domain:
        return "TRUE", []

    tokens = list(domain)
    # Parse first expression
    sql, params = _parse_tokens(tokens, valid_fields)

    # Implicit AND for remaining top-level items
    while tokens:
        right_sql, right_params = _parse_tokens(tokens, valid_fields)
        sql = f"({sql} AND {right_sql})"
        params = params + right_params

    return sql, params


def kwargs_to_domain(kwargs: dict[str, Any]) -> list[tuple]:
    """Convert keyword arguments to a domain expression.

    kwargs_to_domain({"name": "x", "active": True})
    → [("name", "=", "x"), ("active", "=", True)]
    """
    return [(k, "=", v) for k, v in kwargs.items()]


def _parse_tokens(
    tokens: list,
    valid_fields: set[str],
) -> tuple[str, list[Any]]:
    """Recursively parse domain tokens (mutates the list by popping from front)."""
    if not tokens:
        return "TRUE", []

    head = tokens[0]

    # Logical operator
    if head == "&":
        tokens.pop(0)
        left_sql, left_params = _parse_tokens(tokens, valid_fields)
        right_sql, right_params = _parse_tokens(tokens, valid_fields)
        return f"({left_sql} AND {right_sql})", left_params + right_params

    if head == "|":
        tokens.pop(0)
        left_sql, left_params = _parse_tokens(tokens, valid_fields)
        right_sql, right_params = _parse_tokens(tokens, valid_fields)
        return f"({left_sql} OR {right_sql})", left_params + right_params

    if head == "!":
        tokens.pop(0)
        inner_sql, inner_params = _parse_tokens(tokens, valid_fields)
        return f"(NOT {inner_sql})", inner_params

    # Leaf: tuple (field, op, value)
    if isinstance(head, (tuple, list)):
        tokens.pop(0)
        return _leaf_to_sql(head, valid_fields)

    raise ValidationError(f"Invalid domain token: {head!r}")


def _leaf_to_sql(
    leaf: tuple | list,
    valid_fields: set[str],
) -> tuple[str, list[Any]]:
    """Convert a single (field, operator, value) to SQL."""
    if len(leaf) != 3:
        raise ValidationError(f"Domain leaf must have 3 elements, got: {leaf}")

    field, op, value = leaf

    # Validate field name
    if field not in valid_fields:
        raise ValidationError(
            f"Unknown field '{field}' in domain. Valid fields: {sorted(valid_fields)}"
        )

    # Validate operator
    if op not in _VALID_OPERATORS:
        raise ValidationError(
            f"Invalid operator '{op}' in domain. "
            f"Valid operators: {sorted(_VALID_OPERATORS)}"
        )

    # IS NULL / IS NOT NULL
    if op == "is" and value is None:
        return f'"{field}" IS NULL', []
    if op == "is not" and value is None:
        return f'"{field}" IS NOT NULL', []

    # IN / NOT IN
    if op == "in":
        if not isinstance(value, (list, tuple, set)):
            raise ValidationError(
                f"'in' operator requires a list, got {type(value).__name__}"
            )
        if not value:
            return "FALSE", []
        placeholders = ", ".join(["%s"] * len(value))
        return f'"{field}" IN ({placeholders})', list(value)

    if op == "not in":
        if not isinstance(value, (list, tuple, set)):
            raise ValidationError(
                f"'not in' operator requires a list, got {type(value).__name__}"
            )
        if not value:
            return "TRUE", []
        placeholders = ", ".join(["%s"] * len(value))
        return f'"{field}" NOT IN ({placeholders})', list(value)

    # FTS @@
    if op == "@@":
        return f"\"{field}\" @@ plainto_tsquery('simple', %s)", [value]

    # Standard comparison
    sql_op = _OP_SQL[op]
    return f'"{field}" {sql_op} %s', [value]


def parse_order(order: str, valid_fields: set[str]) -> str:
    """Validate and return an ORDER BY clause.

    Accepts: "field1 ASC, field2 DESC" or "field1" (defaults to ASC).
    """
    if not order:
        return ""

    parts = []
    for segment in order.split(","):
        segment = segment.strip()
        if not segment:
            continue
        tokens = segment.split()
        field_name = tokens[0]
        direction = tokens[1].upper() if len(tokens) > 1 else "ASC"

        if field_name not in valid_fields and field_name != "id":
            raise ValidationError(
                f"Unknown field '{field_name}' in ORDER BY. "
                f"Valid fields: {sorted(valid_fields)}"
            )
        if direction not in ("ASC", "DESC"):
            raise ValidationError(f"Invalid ORDER direction: {direction}")

        parts.append(f'"{field_name}" {direction}')

    return "ORDER BY " + ", ".join(parts)
