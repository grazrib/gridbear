"""CSRF Protection Middleware for FastAPI.

Simple token-based CSRF protection using session-stored tokens.
Implemented as pure ASGI middleware to avoid BaseHTTPMiddleware's
anyio TaskGroup cancellation loop (CPU leak).
"""

import secrets
from urllib.parse import parse_qs

from starlette.requests import Request
from starlette.responses import JSONResponse

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


class CSRFMiddleware:
    """Pure ASGI middleware for CSRF protection on unsafe HTTP methods."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        method = scope.get("method", "GET")

        # Skip safe methods
        if method not in UNSAFE_METHODS:
            await self.app(scope, receive, send)
            return

        path = scope["path"]

        # Skip exempt paths
        if path in CSRF_EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        # Skip exempt prefixes (Bearer-token-based APIs)
        if path.startswith(CSRF_EXEMPT_PREFIXES):
            await self.app(scope, receive, send)
            return

        # Skip if no session (unauthenticated requests)
        if not hasattr(request, "session") or not request.session:
            await self.app(scope, receive, send)
            return

        # Read body from receive for CSRF token extraction.
        # We must buffer it and provide a wrapper so downstream can re-read.
        body_parts = []
        while True:
            message = await receive()
            body_parts.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        body = b"".join(body_parts)

        # Provide a receive wrapper that replays the buffered body
        body_sent = False

        async def receive_wrapper():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            # After body is consumed, return disconnect on subsequent calls
            return {"type": "http.disconnect"}

        # Get token from header first (AJAX requests)
        csrf_token = None
        for key, value in scope.get("headers", []):
            if key == b"x-csrf-token":
                csrf_token = value.decode("latin-1")
                break

        # If not in header, check form data
        if not csrf_token:
            content_type = ""
            for key, value in scope.get("headers", []):
                if key == b"content-type":
                    content_type = value.decode("latin-1")
                    break

            if "application/x-www-form-urlencoded" in content_type:
                try:
                    parsed = parse_qs(body.decode("utf-8"))
                    csrf_token = parsed.get("csrf_token", [None])[0]
                except Exception:
                    pass
            elif "multipart/form-data" in content_type:
                try:
                    body_str = body.decode("utf-8", errors="replace")
                    marker = 'name="csrf_token"'
                    idx = body_str.find(marker)
                    if idx != -1:
                        rest = body_str[idx + len(marker) :]
                        val_start = rest.find("\r\n\r\n")
                        if val_start != -1:
                            val_rest = rest[val_start + 4 :]
                            val_end = val_rest.find("\r\n")
                            if val_end != -1:
                                csrf_token = val_rest[:val_end].strip()
                except Exception:
                    pass

        # Special handling for login - first login sets the token
        if path == "/auth/login" and not request.session.get("csrf_token"):
            get_csrf_token(request)
            await self.app(scope, receive_wrapper, send)
            return

        # Validate token
        if not validate_csrf_token(request, csrf_token):
            response = JSONResponse(
                status_code=403,
                content={"detail": "CSRF token validation failed"},
            )
            await response(scope, receive_wrapper, send)
            return

        await self.app(scope, receive_wrapper, send)
