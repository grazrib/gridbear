"""JWT authentication for Executor API.

Features:
- JWT tokens with 15-minute expiration
- In-memory blacklist for token revocation
- Automatic cleanup of expired blacklist entries
- Bootstrap with static token from environment
"""

import logging
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

logger = logging.getLogger(__name__)

security = HTTPBearer()

# JWT Configuration
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_MINUTES = 15
JWT_ISSUER = "gridbear-executor"

# In-memory blacklist for revoked tokens
# Key: jti (JWT ID), Value: expiry timestamp
_token_blacklist: dict[str, float] = {}
_last_cleanup: float = 0
CLEANUP_INTERVAL = 300  # Clean up every 5 minutes


class TokenPayload(BaseModel):
    """JWT token payload."""

    sub: str  # Subject (client identifier)
    jti: str  # JWT ID (for revocation)
    exp: float  # Expiration timestamp
    iat: float  # Issued at timestamp
    iss: str  # Issuer


class TokenResponse(BaseModel):
    """Response for token generation."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = JWT_EXPIRY_MINUTES * 60


def _get_jwt_secret() -> str:
    """Get JWT signing secret from environment.

    Falls back to EXECUTOR_AUTH_TOKEN if JWT_SECRET not set.
    """
    secret = os.environ.get("JWT_SECRET") or os.environ.get("EXECUTOR_AUTH_TOKEN", "")
    if not secret:
        raise RuntimeError("JWT_SECRET or EXECUTOR_AUTH_TOKEN must be configured")
    return secret


def _get_static_token() -> str:
    """Get static bootstrap token from environment."""
    token = os.environ.get("EXECUTOR_AUTH_TOKEN", "")
    if not token:
        raise RuntimeError("EXECUTOR_AUTH_TOKEN not configured")
    return token


def _cleanup_blacklist() -> None:
    """Remove expired entries from blacklist."""
    global _last_cleanup
    now = time.time()

    # Only cleanup every CLEANUP_INTERVAL seconds
    if now - _last_cleanup < CLEANUP_INTERVAL:
        return

    _last_cleanup = now
    expired_jtis = [jti for jti, exp in _token_blacklist.items() if exp < now]

    for jti in expired_jtis:
        del _token_blacklist[jti]

    if expired_jtis:
        logger.debug(f"Cleaned up {len(expired_jtis)} expired blacklist entries")


def create_jwt_token(subject: str = "gridbear") -> TokenResponse:
    """Create a new JWT token.

    Args:
        subject: Client identifier (default: "gridbear")

    Returns:
        TokenResponse with access_token
    """
    now = datetime.now(timezone.utc)
    expiry = now + timedelta(minutes=JWT_EXPIRY_MINUTES)

    payload = {
        "sub": subject,
        "jti": secrets.token_hex(16),
        "exp": expiry.timestamp(),
        "iat": now.timestamp(),
        "iss": JWT_ISSUER,
    }

    token = jwt.encode(payload, _get_jwt_secret(), algorithm=JWT_ALGORITHM)

    return TokenResponse(
        access_token=token,
        expires_in=JWT_EXPIRY_MINUTES * 60,
    )


def verify_jwt_token(token: str) -> TokenPayload:
    """Verify a JWT token.

    Args:
        token: JWT token string

    Returns:
        TokenPayload if valid

    Raises:
        HTTPException: If token is invalid, expired, or blacklisted
    """
    try:
        payload = jwt.decode(
            token,
            _get_jwt_secret(),
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check blacklist
    jti = payload.get("jti")
    if jti and jti in _token_blacklist:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Cleanup blacklist periodically
    _cleanup_blacklist()

    return TokenPayload(**payload)


def revoke_token(jti: str, exp: float) -> None:
    """Add a token to the blacklist.

    Args:
        jti: JWT ID to revoke
        exp: Token expiration timestamp (for cleanup)
    """
    _token_blacklist[jti] = exp
    logger.info(f"Token revoked: {jti[:8]}...")


def is_static_token(token: str) -> bool:
    """Check if token is the static bootstrap token."""
    return token == _get_static_token()


async def verify_token(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
) -> TokenPayload:
    """Verify bearer token (JWT or static).

    Args:
        credentials: HTTP Bearer credentials

    Returns:
        TokenPayload with subject info

    Raises:
        HTTPException: If token is invalid
    """
    token = credentials.credentials

    # First try as static token (for /auth/token endpoint bootstrap)
    if is_static_token(token):
        # Return a synthetic payload for static token
        return TokenPayload(
            sub="bootstrap",
            jti="static",
            exp=time.time() + 3600,  # 1 hour synthetic expiry
            iat=time.time(),
            iss=JWT_ISSUER,
        )

    # Try as JWT
    return verify_jwt_token(token)


# Type alias for dependency injection
TokenDep = Annotated[TokenPayload, Depends(verify_token)]
