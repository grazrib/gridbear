"""OAuth2 Bearer Token Validation Middleware.

Validates Bearer tokens on protected endpoints (e.g., /mcp/*).
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from .models import OAuth2Database


class OAuth2BearerMiddleware(BaseHTTPMiddleware):
    """Middleware that validates Bearer tokens on protected paths.

    Protected paths are matched by prefix (e.g., /mcp/).
    Non-protected paths pass through without token validation.
    """

    def __init__(
        self, app, db: OAuth2Database, protected_prefixes: list[str] | None = None
    ):
        super().__init__(app)
        self.db = db
        self.protected_prefixes = protected_prefixes or ["/mcp/"]

    def _is_protected(self, path: str) -> bool:
        return any(path.startswith(p) for p in self.protected_prefixes)

    async def dispatch(self, request: Request, call_next) -> Response:
        if not self._is_protected(request.url.path):
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={
                    "error": "invalid_token",
                    "error_description": "Bearer token required",
                },
                headers={"WWW-Authenticate": 'Bearer realm="gridbear"'},
            )

        token_string = auth_header[7:]
        token, client = self.db.validate_token(token_string)

        if not token:
            return JSONResponse(
                status_code=401,
                content={
                    "error": "invalid_token",
                    "error_description": "Invalid or expired token",
                },
                headers={
                    "WWW-Authenticate": 'Bearer realm="gridbear", error="invalid_token"'
                },
            )

        # Attach token info to request state for downstream handlers
        request.state.oauth2_token = token
        request.state.oauth2_client = client
        request.state.oauth2_user = token.user_identity
        request.state.oauth2_scope = token.scope
        request.state.oauth2_mcp_permissions = client.get_mcp_permissions_list()

        # Update last used (best effort, non-blocking)
        ip = request.client.host if request.client else None
        self.db.update_last_used(token.id, ip_address=ip)

        return await call_next(request)
