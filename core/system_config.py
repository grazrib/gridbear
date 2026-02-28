"""System-wide key-value configuration backed by PostgreSQL.

Modeled after Odoo's ``ir.config_parameter`` — stores application-level
settings (default_runner, active_theme, mcp_gateway, etc.) in the DB
instead of flat files.

Usage::

    from core.system_config import SystemConfig

    # Async
    runner = await SystemConfig.get_param("default_runner", "claude")
    await SystemConfig.set_param("default_runner", "openai")

    # Sync (for boot paths before event loop)
    runner = SystemConfig.get_param_sync("default_runner", "claude")
    SystemConfig.set_param_sync("default_runner", "openai")
"""

from __future__ import annotations

from typing import Any

from config.logging_config import logger
from core.orm import Model, fields


class SystemConfig(Model):
    """System configuration key-value store.

    Schema ``app``, table ``system_config``.
    Each row is a single configuration parameter.
    """

    _schema = "app"
    _name = "system_config"

    key = fields.Text(required=True, unique=True, index=True)
    value = fields.Json()

    # ── Convenience helpers ──────────────────────────────────────

    @classmethod
    async def get_param(cls, key: str, default: Any = None) -> Any:
        """Get a config parameter by key (async).

        Returns the stored value, or *default* if the key does not exist.
        """
        try:
            row = await cls.get(key=key)
            if row is not None:
                return row["value"] if row["value"] is not None else default
        except Exception as exc:
            logger.debug("SystemConfig.get_param(%s) failed: %s", key, exc)
        return default

    @classmethod
    async def set_param(cls, key: str, value: Any) -> None:
        """Set a config parameter (async). Creates or updates."""
        await cls.create_or_update(
            _conflict_fields=("key",),
            _update_fields=["value"],
            key=key,
            value=value,
        )

    @classmethod
    def get_param_sync(cls, key: str, default: Any = None) -> Any:
        """Get a config parameter by key (sync)."""
        try:
            row = cls.get_sync(key=key)
            if row is not None:
                return row["value"] if row["value"] is not None else default
        except Exception as exc:
            logger.debug("SystemConfig.get_param_sync(%s) failed: %s", key, exc)
        return default

    @classmethod
    def set_param_sync(cls, key: str, value: Any) -> None:
        """Set a config parameter (sync). Creates or updates."""
        cls.create_or_update_sync(
            _conflict_fields=("key",),
            _update_fields=["value"],
            key=key,
            value=value,
        )
