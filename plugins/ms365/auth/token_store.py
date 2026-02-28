"""Secure token storage with PostgreSQL and Fernet encryption."""

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.fernet import Fernet

from config.logging_config import logger
from plugins.ms365.models import MS365Token

SCHEMA_VERSION = 1


class TokenStore:
    """Secure storage for OAuth tokens using PostgreSQL and Fernet encryption."""

    def __init__(self, encryption_key: str | None = None, **kwargs):
        """Initialize token store.

        Args:
            encryption_key: Fernet encryption key (base64 encoded)
            **kwargs: Ignored (backward compat for old db_path parameter)
        """
        if encryption_key:
            self._fernet = Fernet(encryption_key.encode())
        else:
            logger.warning("No encryption key provided, generating temporary key")
            self._fernet = Fernet(Fernet.generate_key())

    def _encrypt(self, data: str) -> bytes:
        """Encrypt string data."""
        return self._fernet.encrypt(data.encode())

    def _decrypt(self, data: bytes) -> str:
        """Decrypt bytes to string."""
        return self._fernet.decrypt(data).decode()

    def store_tokens(
        self,
        tenant_id: str,
        tenant_name: str,
        access_token: str,
        refresh_token: str,
        expires_at: datetime,
        scopes: list[str],
        role: str = "guest",
    ) -> None:
        """Store tokens for a tenant."""
        MS365Token.create_or_update_sync(
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            access_token_encrypted=self._encrypt(access_token),
            refresh_token_encrypted=self._encrypt(refresh_token),
            expires_at=expires_at,
            scopes=json.dumps(scopes),
            role=role,
            schema_version=SCHEMA_VERSION,
            status="active",
            failure_count=0,
        )
        logger.info(f"Stored tokens for tenant {tenant_name} ({tenant_id})")

    def get_tokens(self, tenant_id: str) -> dict[str, Any] | None:
        """Get tokens for a tenant."""
        row = MS365Token.get_sync(tenant_id=tenant_id)
        if not row:
            return None

        return {
            "tenant_id": row["tenant_id"],
            "tenant_name": row["tenant_name"],
            "access_token": self._decrypt(bytes(row["access_token_encrypted"])),
            "refresh_token": self._decrypt(bytes(row["refresh_token_encrypted"])),
            "expires_at": row["expires_at"],
            "scopes": json.loads(row["scopes"]) if row["scopes"] else [],
            "capabilities": (
                json.loads(row["capabilities"]) if row["capabilities"] else None
            ),
            "capabilities_cached_at": row["capabilities_cached_at"],
            "role": row["role"],
            "status": row["status"],
            "failure_count": row["failure_count"],
        }

    def get_all_tenants(self) -> list[dict[str, Any]]:
        """Get all stored tenants."""
        rows = MS365Token.search_sync([])
        return [
            {
                "tenant_id": row["tenant_id"],
                "tenant_name": row["tenant_name"],
                "role": row["role"],
                "status": row["status"],
                "capabilities": (
                    json.loads(row["capabilities"]) if row["capabilities"] else None
                ),
                "capabilities_cached_at": row["capabilities_cached_at"],
                "failure_count": row["failure_count"],
            }
            for row in rows
        ]

    def update_capabilities(self, tenant_id: str, capabilities: dict[str, Any]) -> None:
        """Update cached capabilities for a tenant."""
        MS365Token.write_sync(
            tenant_id,
            capabilities=json.dumps(capabilities),
            capabilities_cached_at=datetime.now(timezone.utc),
        )

    def mark_failure(self, tenant_id: str) -> int:
        """Increment failure count for a tenant. Returns new count."""
        # Arithmetic increment requires raw SQL
        rows = MS365Token.raw_search_sync(
            'UPDATE {table} SET "failure_count" = "failure_count" + 1, '
            '"updated_at" = %s WHERE "tenant_id" = %s RETURNING failure_count',
            (datetime.now(timezone.utc), tenant_id),
        )
        failure_count = rows[0]["failure_count"] if rows else 0

        if failure_count >= 3:
            MS365Token.write_sync(tenant_id, status="offline")
            logger.warning(
                f"Tenant {tenant_id} marked as offline after {failure_count} failures"
            )

        return failure_count

    def mark_active(self, tenant_id: str) -> None:
        """Mark tenant as active and reset failure count."""
        MS365Token.write_sync(
            tenant_id,
            status="active",
            failure_count=0,
        )

    def delete_tenant(self, tenant_id: str) -> None:
        """Delete tokens for a tenant."""
        MS365Token.delete_sync(tenant_id)
        logger.info(f"Deleted tokens for tenant {tenant_id}")

    def is_token_expired(self, tenant_id: str, buffer_seconds: int = 300) -> bool:
        """Check if token is expired or about to expire."""
        tokens = self.get_tokens(tenant_id)
        if not tokens:
            return True

        expires_at = tokens["expires_at"]
        now = datetime.now(timezone.utc)
        threshold = now + timedelta(seconds=buffer_seconds)
        return expires_at <= threshold
