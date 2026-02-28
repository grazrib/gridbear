"""CSRF Protection Middleware for FastAPI.

Simple token-based CSRF protection using session-stored tokens.
"""

import secrets
from urllib.parse import parse_qs

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

# Methods that modify state and require CSRF validation
UNSAFE_METHODS = {"POST", "PUT", "DELETE", "PATCH"}

# Routes exempt from CSRF (e.g., API endpoints with other auth)
CSRF_EXEMPT_PATHS = {
    "/oauth/gmail/callback",  # OAuth callback (state parameter protection)
    "/auth/login",  # Login form sets the token, validated on subsequent requests
    "/oauth2/token",  # OAuth2 token endpoint (client auth, not session)
    "/oauth2/revoke",  # OAuth2 revocation (client auth, not session)
    "/oauth2/register",  # OAuth2 dynamic registration (no auth)
    "/mcp",  # MCP Gateway (Bearer token auth, not session)
    "/notifications/internal/create",  # Internal API (Bearer token auth)
}

# Path prefixes exempt from CSRF (Bearer token auth, not session-based)
CSRF_EXEMPT_PREFIXES = (
    "/api/",  # REST API (Bearer token auth)
)


def generate_csrf_token() -> str:
    """Generate a cryptographically secure CSRF token."""
    return secrets.token_hex(32)


def get_csrf_token(request: Request) -> str:
    """Get or create CSRF token from session."""
    if "csrf_token" not in request.session:
        request.session["csrf_token"] = generate_csrf_token()
    return request.session["csrf_token"]


def validate_csrf_token(request: Request, token: str | None) -> bool:
    """Validate CSRF token against session token."""
    session_token = request.session.get("csrf_token")
    if not session_token or not token:
        return False
    return secrets.compare_digest(session_token, token)


class CSRFMiddleware(BaseHTTPMiddleware):
    """Middleware for CSRF protection on unsafe HTTP methods."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip safe methods
        if request.method not in UNSAFE_METHODS:
            return await call_next(request)

        # Skip exempt paths
        if request.url.path in CSRF_EXEMPT_PATHS:
            return await call_next(request)

        # Skip exempt prefixes (Bearer-token-based APIs)
        if request.url.path.startswith(CSRF_EXEMPT_PREFIXES):
            return await call_next(request)

        # Skip if no session (unauthenticated requests)
        if not hasattr(request, "session") or not request.session:
            return await call_next(request)

        # Get token from form data or header
        csrf_token = None

        # Check header first (for AJAX requests)
        csrf_token = request.headers.get("X-CSRF-Token")

        # If not in header, check form data by reading raw body
        # We avoid request.form() because BaseHTTPMiddleware causes issues
        # with body consumption - FastAPI can't read it again
        if not csrf_token:
            content_type = request.headers.get("content-type", "")
            if "application/x-www-form-urlencoded" in content_type:
                # Read raw body and parse it manually
                body = await request.body()
                try:
                    parsed = parse_qs(body.decode("utf-8"))
                    csrf_token = parsed.get("csrf_token", [None])[0]
                except Exception:
                    pass
            elif "multipart/form-data" in content_type:
                # For multipart forms, extract csrf_token from the boundary-delimited body
                body = await request.body()
                try:
                    # Find csrf_token field in multipart body
                    body_str = body.decode("utf-8", errors="replace")
                    marker = 'name="csrf_token"'
                    idx = body_str.find(marker)
                    if idx != -1:
                        # Value follows after double newline
                        rest = body_str[idx + len(marker) :]
                        # Skip \r\n\r\n
                        val_start = rest.find("\r\n\r\n")
                        if val_start != -1:
                            val_rest = rest[val_start + 4 :]
                            # Value ends at next boundary (line starting with --)
                            val_end = val_rest.find("\r\n")
                            if val_end != -1:
                                csrf_token = val_rest[:val_end].strip()
                except Exception:
                    pass

        # Special handling for login - first login sets the token
        if request.url.path == "/auth/login" and not request.session.get("csrf_token"):
            # First login attempt, generate token for next request
            get_csrf_token(request)
            return await call_next(request)

        # Validate token
        if not validate_csrf_token(request, csrf_token):
            raise HTTPException(status_code=403, detail="CSRF token validation failed")

        return await call_next(request)
