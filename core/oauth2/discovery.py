"""OAuth2 Discovery Endpoints.

RFC 8414 - OAuth 2.0 Authorization Server Metadata
RFC 8707 - Resource Indicators for OAuth 2.0
"""

import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


def _get_issuer(request: Request) -> str:
    """Derive issuer URL (respects GRIDBEAR_BASE_URL for proxied setups)."""
    base = os.getenv("GRIDBEAR_BASE_URL", "").rstrip("/")
    if base:
        return base
    return str(request.base_url).rstrip("/")


@router.get("/.well-known/oauth-authorization-server")
async def authorization_server_metadata(request: Request):
    """RFC 8414 - Authorization Server Metadata."""
    issuer = _get_issuer(request)

    metadata = {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/oauth2/authorize",
        "token_endpoint": f"{issuer}/oauth2/token",
        "userinfo_endpoint": f"{issuer}/oauth2/userinfo",
        "revocation_endpoint": f"{issuer}/oauth2/revoke",
        "registration_endpoint": f"{issuer}/oauth2/register",
        "response_types_supported": ["code"],
        "grant_types_supported": [
            "authorization_code",
            "client_credentials",
            "refresh_token",
        ],
        "token_endpoint_auth_methods_supported": [
            "client_secret_post",
            "none",
        ],
        "code_challenge_methods_supported": ["S256"],
        "scopes_supported": [
            "openid",
            "profile",
            "email",
            "mcp",
            "api",
        ],
        "service_documentation": f"{issuer}/docs",
    }

    return JSONResponse(
        content=metadata,
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/.well-known/oauth-protected-resource")
async def protected_resource_metadata(request: Request):
    """RFC 8707 - Protected Resource Metadata.

    Tells MCP clients where to authenticate to access the MCP gateway.
    """
    issuer = _get_issuer(request)

    metadata = {
        "resource": f"{issuer}/mcp",
        "authorization_servers": [issuer],
        "bearer_methods_supported": ["header"],
        "scopes_supported": ["mcp"],
    }

    return JSONResponse(
        content=metadata,
        headers={"Cache-Control": "public, max-age=3600"},
    )
