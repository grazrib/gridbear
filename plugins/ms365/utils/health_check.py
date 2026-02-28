"""Health check utilities for MS365 plugin."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from config.logging_config import logger


@dataclass
class TenantHealth:
    """Health status for a tenant."""

    tenant_id: str
    tenant_name: str
    is_healthy: bool
    last_check: datetime
    failure_count: int
    error_message: str | None = None


async def check_tenant_health(
    graph_client: Any,
    oauth_manager: Any,
    tenant_id: str,
    tenant_name: str,
) -> TenantHealth:
    """Check health of a single tenant.

    Args:
        graph_client: GraphClient instance
        oauth_manager: OAuthManager instance
        tenant_id: Tenant ID
        tenant_name: Tenant name

    Returns:
        TenantHealth status
    """
    now = datetime.now(timezone.utc)

    try:
        token = await oauth_manager.get_valid_token(tenant_id)
        if not token:
            return TenantHealth(
                tenant_id=tenant_id,
                tenant_name=tenant_name,
                is_healthy=False,
                last_check=now,
                failure_count=1,
                error_message="Could not obtain valid token",
            )

        # Simple health check - get user profile
        user = await graph_client.get_me(token)

        if user and "id" in user:
            return TenantHealth(
                tenant_id=tenant_id,
                tenant_name=tenant_name,
                is_healthy=True,
                last_check=now,
                failure_count=0,
            )
        else:
            return TenantHealth(
                tenant_id=tenant_id,
                tenant_name=tenant_name,
                is_healthy=False,
                last_check=now,
                failure_count=1,
                error_message="Invalid response from Graph API",
            )

    except Exception as e:
        return TenantHealth(
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            is_healthy=False,
            last_check=now,
            failure_count=1,
            error_message=str(e),
        )


async def check_all_tenants(
    graph_client: Any,
    oauth_manager: Any,
    token_store: Any,
) -> list[TenantHealth]:
    """Check health of all tenants.

    Args:
        graph_client: GraphClient instance
        oauth_manager: OAuthManager instance
        token_store: TokenStore instance

    Returns:
        List of TenantHealth statuses
    """
    tenants = token_store.get_all_tenants()

    tasks = [
        check_tenant_health(
            graph_client,
            oauth_manager,
            tenant["tenant_id"],
            tenant["tenant_name"],
        )
        for tenant in tenants
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    health_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            tenant = tenants[i]
            health_results.append(
                TenantHealth(
                    tenant_id=tenant["tenant_id"],
                    tenant_name=tenant["tenant_name"],
                    is_healthy=False,
                    last_check=datetime.now(timezone.utc),
                    failure_count=1,
                    error_message=str(result),
                )
            )
        else:
            health_results.append(result)

    # Update token store based on health results
    for health in health_results:
        if health.is_healthy:
            token_store.mark_active(health.tenant_id)
        else:
            token_store.mark_failure(health.tenant_id)
            logger.warning(
                f"Tenant {health.tenant_name} unhealthy: {health.error_message}"
            )

    return health_results
