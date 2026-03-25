"""Internal vault API for MCP subprocess secret access.

Provides get/list endpoints authenticated via INTERNAL_API_SECRET,
used by MCP server subprocesses (e.g. agentic-development) to read
secrets from the secrets manager at runtime.
"""

from fastapi import APIRouter, Depends, Request

from core.api_schemas import api_error, api_ok
from core.internal_api.auth import verify_internal_auth

router = APIRouter(prefix="/api/vault", tags=["vault-api"])


@router.get("/get")
async def vault_get(
    request: Request,
    key: str = "",
    _auth: None = Depends(verify_internal_auth),
):
    """Get a secret value by key."""
    if not key:
        return api_error(400, "key parameter required", "validation_error")

    from ui.secrets_manager import secrets_manager

    value = secrets_manager.get_plain(key)
    if value is None:
        return api_error(404, f"Key '{key}' not found", "not_found")

    return api_ok(data={"value": value})


@router.get("/list")
async def vault_list(
    request: Request,
    prefix: str = "",
    _auth: None = Depends(verify_internal_auth),
):
    """List secret key names matching a prefix."""
    from ui.secrets_manager import secrets_manager

    all_entries = secrets_manager.list_keys()
    all_names = [e["key_name"] for e in all_entries]
    if prefix:
        keys = [k for k in all_names if k.startswith(prefix)]
    else:
        keys = all_names

    return api_ok(data={"keys": sorted(keys)})
