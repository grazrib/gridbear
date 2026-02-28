"""Tests for Claude CLI OAuth token auto-refresh logic.

Verifies:
1. No refresh when token is still valid (>5 min remaining)
2. No refresh when expiresAt is 0 (manual token setup)
3. No refresh when refreshToken is empty
4. Successful refresh updates secrets and returns new block
5. Failed refresh returns None (graceful degradation)
6. New refresh token from server is picked up
7. _get_cli_env() returns refreshed token
"""

import time
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_refresh_lock():
    """Ensure the refresh lock is released between tests."""
    # Re-create the lock to avoid cross-test deadlocks
    import threading

    import plugins.claude.api.routes as routes_mod

    routes_mod._refresh_lock = threading.Lock()
    yield


def _make_oauth_block(
    access_token="old-access-token",
    refresh_token="valid-refresh-token",
    expires_at_ms=None,
):
    """Build a mock oauth block with configurable expiry."""
    if expires_at_ms is None:
        # Default: expired 10 minutes ago
        expires_at_ms = int((time.time() - 600) * 1000)
    return {
        "accessToken": access_token,
        "refreshToken": refresh_token,
        "expiresAt": expires_at_ms,
        "scopes": ["user:inference"],
    }


def _make_token_response(
    access_token="new-access-token",
    refresh_token="new-refresh-token",
    expires_in=3600,
):
    """Build a mock token endpoint response."""
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": expires_in,
        "scope": "user:inference user:profile",
    }


class TestRefreshOauthToken:
    """Tests for _refresh_oauth_token()."""

    def test_no_refresh_when_token_still_valid(self):
        """Token with >5 min remaining should not trigger refresh."""
        from plugins.claude.api.routes import _refresh_oauth_token

        # Expires in 10 minutes — no refresh needed
        block = _make_oauth_block(
            expires_at_ms=int((time.time() + 600) * 1000),
        )
        result = _refresh_oauth_token(block)
        assert result is None

    def test_no_refresh_when_expires_at_zero(self):
        """Manual token setup (expiresAt=0) should skip refresh."""
        from plugins.claude.api.routes import _refresh_oauth_token

        block = _make_oauth_block(expires_at_ms=0)
        result = _refresh_oauth_token(block)
        assert result is None

    def test_no_refresh_when_no_refresh_token(self):
        """Missing refreshToken should skip refresh."""
        from plugins.claude.api.routes import _refresh_oauth_token

        block = _make_oauth_block(refresh_token="")
        result = _refresh_oauth_token(block)
        assert result is None

    @patch("plugins.claude.api.routes._save_credentials_to_secrets")
    @patch("plugins.claude.api.routes._read_credentials_from_secrets")
    def test_successful_refresh(self, mock_read, mock_save):
        """Expired token with valid refresh token should refresh."""
        from plugins.claude.api.routes import _refresh_oauth_token

        block = _make_oauth_block()
        # Double-check read returns stale block (simulating no other thread refreshed)
        mock_read.return_value = block

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _make_token_response()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response

        with patch("httpx.Client", return_value=mock_client):
            result = _refresh_oauth_token(block)

        assert result is not None
        assert result["accessToken"] == "new-access-token"
        assert result["refreshToken"] == "new-refresh-token"
        assert result["expiresAt"] > int(time.time() * 1000)
        mock_save.assert_called_once()

    @patch("plugins.claude.api.routes._save_credentials_to_secrets")
    @patch("plugins.claude.api.routes._read_credentials_from_secrets")
    def test_failed_refresh_returns_none(self, mock_read, mock_save):
        """Failed HTTP refresh should return None, not raise."""
        from plugins.claude.api.routes import _refresh_oauth_token

        block = _make_oauth_block()
        mock_read.return_value = block

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "invalid_grant"

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response

        with patch("httpx.Client", return_value=mock_client):
            result = _refresh_oauth_token(block)

        assert result is None
        mock_save.assert_not_called()

    @patch("plugins.claude.api.routes._save_credentials_to_secrets")
    @patch("plugins.claude.api.routes._read_credentials_from_secrets")
    def test_network_error_returns_none(self, mock_read, mock_save):
        """Network error during refresh should return None."""
        from plugins.claude.api.routes import _refresh_oauth_token

        block = _make_oauth_block()
        mock_read.return_value = block

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = ConnectionError("network down")

        with patch("httpx.Client", return_value=mock_client):
            result = _refresh_oauth_token(block)

        assert result is None
        mock_save.assert_not_called()

    @patch("plugins.claude.api.routes._save_credentials_to_secrets")
    @patch("plugins.claude.api.routes._read_credentials_from_secrets")
    def test_server_omits_new_refresh_token(self, mock_read, mock_save):
        """If server doesn't return a new refresh_token, keep the old one."""
        from plugins.claude.api.routes import _refresh_oauth_token

        block = _make_oauth_block(refresh_token="original-refresh")
        mock_read.return_value = block

        token_resp = _make_token_response()
        del token_resp["refresh_token"]  # Server omits it

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = token_resp

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response

        with patch("httpx.Client", return_value=mock_client):
            result = _refresh_oauth_token(block)

        assert result is not None
        assert result["refreshToken"] == "original-refresh"

    @patch("plugins.claude.api.routes._read_credentials_from_secrets")
    def test_double_check_skips_refresh_when_another_thread_refreshed(self, mock_read):
        """Double-check pattern: if secrets now show fresh token, skip HTTP call."""
        from plugins.claude.api.routes import _refresh_oauth_token

        block = _make_oauth_block()
        # After acquiring lock, re-read returns a fresh token
        fresh_block = _make_oauth_block(
            access_token="already-refreshed",
            expires_at_ms=int((time.time() + 3600) * 1000),
        )
        mock_read.return_value = fresh_block

        result = _refresh_oauth_token(block)
        assert result is not None
        assert result["accessToken"] == "already-refreshed"


class TestGetCliEnvRefresh:
    """Test that _get_cli_env() triggers refresh when needed."""

    @patch("plugins.claude.api.routes._refresh_oauth_token")
    @patch("plugins.claude.api.routes._read_credentials_from_secrets")
    def test_cli_env_uses_refreshed_token(self, mock_read, mock_refresh):
        """_get_cli_env() should use refreshed token when available."""
        from plugins.claude.api.routes import _get_cli_env

        stale_block = _make_oauth_block()
        fresh_block = _make_oauth_block(access_token="fresh-token")

        mock_read.return_value = stale_block
        mock_refresh.return_value = fresh_block

        env = _get_cli_env()
        assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "fresh-token"
        mock_refresh.assert_called_once_with(stale_block)

    @patch("plugins.claude.api.routes._refresh_oauth_token")
    @patch("plugins.claude.api.routes._read_credentials_from_secrets")
    def test_cli_env_uses_existing_when_refresh_not_needed(
        self, mock_read, mock_refresh
    ):
        """_get_cli_env() uses existing token when refresh returns None."""
        from plugins.claude.api.routes import _get_cli_env

        block = _make_oauth_block(access_token="still-valid")
        mock_read.return_value = block
        mock_refresh.return_value = None

        env = _get_cli_env()
        assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "still-valid"
