import hmac
import os

from fastapi import Header, HTTPException


def verify_internal_auth(authorization: str = Header(...)):
    """Verify shared secret for internal API calls."""
    expected = os.getenv("INTERNAL_API_SECRET", "")
    if not expected or not hmac.compare_digest(authorization, f"Bearer {expected}"):
        raise HTTPException(status_code=403, detail="Unauthorized")
