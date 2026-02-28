"""GridBear Admin Authentication Module.

Provides multi-user authentication with:
- Username/password login
- TOTP-based 2FA (Google Authenticator compatible)
- Recovery codes for 2FA bypass
- Persistent database-backed sessions
- Audit logging
"""

from ui.auth.database import AuthDatabase, init_auth_db
from ui.auth.recovery import RecoveryCodeManager
from ui.auth.session import SessionManager, get_current_user
from ui.auth.totp import TOTPManager

__all__ = [
    "AuthDatabase",
    "init_auth_db",
    "SessionManager",
    "get_current_user",
    "TOTPManager",
    "RecoveryCodeManager",
]
