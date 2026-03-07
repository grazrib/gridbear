"""Tenant context — async-safe ContextVar for multi-tenancy isolation.

Follows the same ContextVar pattern as ``core/i18n.py`` (``current_lang``).
Each asyncio Task inherits the parent's value but can override independently.
"""

from __future__ import annotations

from contextvars import ContextVar

SUPERADMIN_BYPASS = -1
"""Sentinel value: allows cross-tenant reads; raises on create (must specify explicitly)."""

_current_tenant: ContextVar[int | None] = ContextVar("tenant", default=None)
_user_companies: ContextVar[tuple[int, ...]] = ContextVar("user_companies", default=())


def set_tenant(company_id: int, user_companies: tuple[int, ...] | None = None) -> None:
    """Set the active tenant for the current async context.

    Args:
        company_id: Active company ID, or SUPERADMIN_BYPASS for cross-tenant.
        user_companies: All companies the user belongs to (for multi-company queries).
    """
    _current_tenant.set(company_id)
    if user_companies is not None:
        _user_companies.set(user_companies)
    elif company_id != SUPERADMIN_BYPASS:
        _user_companies.set((company_id,))


def get_tenant() -> int | None:
    """Return the current tenant ID, SUPERADMIN_BYPASS, or None."""
    return _current_tenant.get()


def get_user_companies() -> tuple[int, ...]:
    """Return all company IDs the current user belongs to."""
    return _user_companies.get()


def clear_tenant() -> None:
    """Reset tenant context to None."""
    _current_tenant.set(None)
    _user_companies.set(())
