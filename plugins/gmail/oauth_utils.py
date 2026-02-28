"""Gmail OAuth utility functions.

Shared between the plugin admin routes and the user portal (admin/routes/me.py).
"""

import json
import re
from pathlib import Path

from ui.secrets_manager import secrets_manager

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CREDENTIALS_DIR = BASE_DIR / "credentials"

# Claude Code settings path (mounted from host)
CLAUDE_SETTINGS_PATH = Path("/root/.claude/settings.json")

# OAuth scopes for Gmail, Calendar, and Google Workspace
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Base OAuth credentials (shared across all users)
OAUTH_CREDENTIALS_PATH = CREDENTIALS_DIR / "oauth_client.json"


def get_flow(redirect_uri: str):
    """Create OAuth flow with redirect URI."""
    from fastapi import HTTPException
    from google_auth_oauthlib.flow import Flow

    if not OAUTH_CREDENTIALS_PATH.exists():
        raise HTTPException(
            status_code=500,
            detail="OAuth credentials not configured. Place oauth_client.json in credentials/",
        )

    flow = Flow.from_client_secrets_file(
        str(OAUTH_CREDENTIALS_PATH),
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )
    return flow


def add_gmail_tool_permission(email: str) -> bool:
    """Add Gmail tool permission to Claude Code settings.json."""
    sanitized = re.sub(r"[@.]", "_", email)
    permission_pattern = f"mcp__gmail-{sanitized}__*"

    try:
        if not CLAUDE_SETTINGS_PATH.exists():
            return False

        with open(CLAUDE_SETTINGS_PATH, "r") as f:
            settings = json.load(f)

        if "permissions" not in settings:
            settings["permissions"] = {}
        if "allow" not in settings["permissions"]:
            settings["permissions"]["allow"] = []

        if permission_pattern in settings["permissions"]["allow"]:
            return False

        settings["permissions"]["allow"].append(permission_pattern)

        with open(CLAUDE_SETTINGS_PATH, "w") as f:
            json.dump(settings, f, indent=2)

        return True
    except Exception:
        return False


def trigger_mcp_reload(email: str):
    """Request reload of Gmail and GWS MCP plugins after OAuth token update."""
    import time

    reload_file = BASE_DIR / "data" / "reload_requests.json"
    reload_file.parent.mkdir(parents=True, exist_ok=True)

    requests = []
    if reload_file.exists():
        try:
            with open(reload_file) as f:
                requests = json.load(f)
        except (json.JSONDecodeError, OSError):
            requests = []

    for plugin in ["gmail", "google-workspace"]:
        requests.append(
            {
                "plugin": plugin,
                "timestamp": time.time(),
                "status": "pending",
                "reason": f"OAuth token updated for {email}",
            }
        )

    with open(reload_file, "w") as f:
        json.dump(requests, f, indent=2)


def has_token(email: str) -> bool:
    """Check if token exists for email in secrets.db."""
    secret_key = f"gmail_token_{email}"
    return secrets_manager.exists(secret_key)


def store_token(email: str, token_data: dict) -> None:
    """Store OAuth token encrypted in secrets.db."""
    secret_key = f"gmail_token_{email}"
    secrets_manager.set(
        secret_key, json.dumps(token_data), description=f"Gmail OAuth token for {email}"
    )


def delete_token(email: str) -> None:
    """Delete OAuth token from secrets.db."""
    secret_key = f"gmail_token_{email}"
    secrets_manager.delete(secret_key)
