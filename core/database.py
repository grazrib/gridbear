"""Centralized PostgreSQL database manager for GridBear.

Provides async and sync connection pools via psycopg3.
Used by both main container (main.py) and admin container (admin/app.py).
Access via core.registry.get_database().
"""

import logging
from contextlib import asynccontextmanager, contextmanager
from typing import Any
from urllib.parse import urlparse

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool, ConnectionPool

logger = logging.getLogger("gridbear")

# Security: reject known default/insecure passwords at startup
_KNOWN_INSECURE_PASSWORDS = frozenset(
    {"evolution_secret", "postgres", "password", "changeme"}
)


class DatabaseManager:
    """Manages PostgreSQL connection pools (async + sync).

    Usage:
        db = DatabaseManager("postgresql://gridbear:pass@host:5432/gridbear")
        await db.initialize()

        async with db.acquire() as conn:
            await conn.execute("SELECT 1")

        await db.shutdown()
    """

    def __init__(self, database_url: str):
        self._validate_url(database_url)
        self._url = database_url
        self._async_pool: AsyncConnectionPool | None = None
        self._sync_pool: ConnectionPool | None = None

    @staticmethod
    def _validate_url(url: str) -> None:
        """Reject empty or known-insecure database passwords."""
        parsed = urlparse(url)
        pw = parsed.password or ""
        if not pw:
            raise RuntimeError(
                "DATABASE_URL has no password. "
                "Set POSTGRES_PASSWORD in .env before starting."
            )
        if pw in _KNOWN_INSECURE_PASSWORDS:
            raise RuntimeError(
                f"DATABASE_URL uses a known insecure password ({pw!r}). "
                "Set a strong POSTGRES_PASSWORD in .env before starting."
            )

    @property
    def url(self) -> str:
        return self._url

    async def initialize(self) -> None:
        """Create connection pools and verify connectivity."""
        logger.info("Initializing PostgreSQL connection pools...")

        self._async_pool = AsyncConnectionPool(
            self._url,
            min_size=2,
            max_size=10,
            open=False,
            kwargs={"row_factory": dict_row},
        )
        await self._async_pool.open()

        self._sync_pool = ConnectionPool(
            self._url,
            min_size=1,
            max_size=5,
            open=False,
            kwargs={"row_factory": dict_row},
        )
        self._sync_pool.open()

        # Verify connectivity
        async with self._async_pool.connection() as conn:
            await conn.execute("SELECT 1")

        logger.info("PostgreSQL connection pool initialized")

    async def shutdown(self) -> None:
        """Close all connection pools."""
        if self._async_pool:
            await self._async_pool.close()
            self._async_pool = None
        if self._sync_pool:
            self._sync_pool.close()
            self._sync_pool = None
        logger.info("PostgreSQL connection pools closed")

    @asynccontextmanager
    async def acquire(self):
        """Acquire an async connection from the pool."""
        if not self._async_pool:
            raise RuntimeError("DatabaseManager not initialized")
        async with self._async_pool.connection() as conn:
            yield conn

    @contextmanager
    def acquire_sync(self):
        """Acquire a sync connection from the pool."""
        if not self._sync_pool:
            raise RuntimeError("DatabaseManager not initialized")
        with self._sync_pool.connection() as conn:
            yield conn

    async def execute(self, query: str, params: tuple | None = None) -> None:
        """Execute a query (no return value)."""
        async with self.acquire() as conn:
            await conn.execute(query, params)

    async def fetch_one(
        self, query: str, params: tuple | None = None
    ) -> dict[str, Any] | None:
        """Execute a query and return a single row as dict."""
        async with self.acquire() as conn:
            cur = await conn.execute(query, params)
            return await cur.fetchone()

    async def fetch_all(
        self, query: str, params: tuple | None = None
    ) -> list[dict[str, Any]]:
        """Execute a query and return all rows as list of dicts."""
        async with self.acquire() as conn:
            cur = await conn.execute(query, params)
            return await cur.fetchall()
