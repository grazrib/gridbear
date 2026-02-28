"""REST API authentication via OAuth2 Bearer token."""

import logging

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)


async def require_api_auth(request: Request) -> dict:
    """FastAPI dependency: validate Bearer token and require 'api' scope."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")

    token_string = auth[7:]

    from core.oauth2.server import get_db

    db = get_db()
    token, client = db.validate_token(token_string)

    if not token or not token.is_valid():
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    scopes = set(token.scope.split()) if token.scope else set()
    if "api" not in scopes:
        raise HTTPException(status_code=403, detail="Scope 'api' required")

    return {"token": token, "client": client, "scopes": scopes}
