"""OAuth2 client registration and token management for the CLI."""

import json
import os
import time

import httpx

from cli.config import CONFIG_DIR

CLIENT_FILE = CONFIG_DIR / "client.json"
TOKEN_FILE = CONFIG_DIR / "token.json"


class AuthError(Exception):
    pass


def _ensure_config_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _write_secure(path, data: dict):
    """Write JSON file with 0600 permissions."""
    _ensure_config_dir()
    path.write_text(json.dumps(data, indent=2))
    os.chmod(path, 0o600)


def _read_json(path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def login(gateway_url: str, session_name: str | None = None) -> dict:
    """Register an OAuth2 client and obtain an access token.

    Returns dict with client_id, access_token, expires_at.
    """
    agent_name = f"cli-{session_name}" if session_name else "cli"

    # Step 1: Dynamic Client Registration
    reg_payload = {
        "client_name": "gridbear-cli",
        "token_endpoint_auth_method": "client_secret_post",
        "scope": "mcp api",
        "agent_name": agent_name,
    }

    with httpx.Client(timeout=15) as http:
        resp = http.post(f"{gateway_url}/oauth2/register", json=reg_payload)
        if resp.status_code != 201:
            detail = (
                resp.json()
                if resp.headers.get("content-type", "").startswith("application/json")
                else resp.text
            )
            raise AuthError(f"Registration failed ({resp.status_code}): {detail}")

        reg = resp.json()
        client_id = reg["client_id"]
        client_secret = reg.get("client_secret")

        if not client_secret:
            raise AuthError("Server did not return a client_secret")

        _write_secure(
            CLIENT_FILE,
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "agent_name": agent_name,
                "gateway_url": gateway_url,
            },
        )

        # Step 2: Token request via client_credentials
        token_resp = http.post(
            f"{gateway_url}/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "mcp api",
            },
        )
        if token_resp.status_code != 200:
            detail = (
                token_resp.json()
                if token_resp.headers.get("content-type", "").startswith(
                    "application/json"
                )
                else token_resp.text
            )
            raise AuthError(
                f"Token request failed ({token_resp.status_code}): {detail}"
            )

        token_data = token_resp.json()
        expires_in = token_data.get("expires_in", 3600)
        token_info = {
            "access_token": token_data["access_token"],
            "token_type": token_data.get("token_type", "Bearer"),
            "expires_at": int(time.time()) + expires_in,
            "scope": token_data.get("scope", ""),
        }
        _write_secure(TOKEN_FILE, token_info)

    return {
        "client_id": client_id,
        "agent_name": agent_name,
        "access_token": token_info["access_token"],
        "expires_at": token_info["expires_at"],
    }


def logout(gateway_url: str):
    """Delete stored client and token files."""
    for f in (TOKEN_FILE, CLIENT_FILE):
        if f.exists():
            f.unlink()


def get_token(gateway_url: str) -> str:
    """Get a valid access token, re-authenticating if expired."""
    token_info = _read_json(TOKEN_FILE)
    if token_info and token_info.get("expires_at", 0) > time.time() + 60:
        return token_info["access_token"]

    # Token expired or missing — try to re-auth with stored client
    client_info = _read_json(CLIENT_FILE)
    if not client_info:
        raise AuthError("Not logged in. Run 'gridbear login' first.")

    with httpx.Client(timeout=15) as http:
        resp = http.post(
            f"{gateway_url}/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": client_info["client_id"],
                "client_secret": client_info["client_secret"],
                "scope": "mcp api",
            },
        )
        if resp.status_code != 200:
            raise AuthError("Session expired and re-auth failed. Run 'gridbear login'.")

        token_data = resp.json()
        expires_in = token_data.get("expires_in", 3600)
        new_info = {
            "access_token": token_data["access_token"],
            "token_type": token_data.get("token_type", "Bearer"),
            "expires_at": int(time.time()) + expires_in,
            "scope": token_data.get("scope", ""),
        }
        _write_secure(TOKEN_FILE, new_info)
        return new_info["access_token"]


def whoami() -> dict:
    """Return stored client + token info (no secrets)."""
    client = _read_json(CLIENT_FILE)
    token = _read_json(TOKEN_FILE)

    if not client:
        return {"logged_in": False}

    result = {
        "logged_in": True,
        "client_id": client.get("client_id"),
        "agent_name": client.get("agent_name"),
        "gateway_url": client.get("gateway_url"),
    }

    if token:
        expires_at = token.get("expires_at", 0)
        result["token_valid"] = expires_at > time.time()
        result["expires_at"] = expires_at
        result["scope"] = token.get("scope", "")

    return result
