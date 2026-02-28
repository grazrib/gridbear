"""Tests for CLI OAuth2 auth — login, token management, whoami."""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from cli.auth import AuthError, get_token, login, logout, whoami


@pytest.fixture
def tmp_config_dir(tmp_path):
    """Use a temp dir for CLI config files."""
    with (
        patch("cli.auth.CONFIG_DIR", tmp_path),
        patch("cli.auth.CLIENT_FILE", tmp_path / "client.json"),
        patch("cli.auth.TOKEN_FILE", tmp_path / "token.json"),
    ):
        yield tmp_path


class TestLogin:
    def test_login_success(self, tmp_config_dir):
        """Login should register client and obtain token."""
        mock_register_resp = MagicMock()
        mock_register_resp.status_code = 201
        mock_register_resp.headers = {"content-type": "application/json"}
        mock_register_resp.json.return_value = {
            "client_id": "cid-123",
            "client_secret": "sec-456",
        }

        mock_token_resp = MagicMock()
        mock_token_resp.status_code = 200
        mock_token_resp.headers = {"content-type": "application/json"}
        mock_token_resp.json.return_value = {
            "access_token": "tok-789",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "mcp api",
        }

        mock_http = MagicMock()
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_http.post.side_effect = [mock_register_resp, mock_token_resp]

        with patch("cli.auth.httpx.Client", return_value=mock_http):
            result = login("http://localhost:8088")

        assert result["client_id"] == "cid-123"
        assert result["agent_name"] == "cli"
        assert result["access_token"] == "tok-789"

        # Verify files were created
        client_file = tmp_config_dir / "client.json"
        assert client_file.exists()
        client_data = json.loads(client_file.read_text())
        assert client_data["client_id"] == "cid-123"

        token_file = tmp_config_dir / "token.json"
        assert token_file.exists()
        token_data = json.loads(token_file.read_text())
        assert token_data["access_token"] == "tok-789"

    def test_login_with_session_name(self, tmp_config_dir):
        """Session name should create agent_name=cli-{name}."""
        mock_register_resp = MagicMock()
        mock_register_resp.status_code = 201
        mock_register_resp.headers = {"content-type": "application/json"}
        mock_register_resp.json.return_value = {
            "client_id": "cid",
            "client_secret": "sec",
        }

        mock_token_resp = MagicMock()
        mock_token_resp.status_code = 200
        mock_token_resp.headers = {"content-type": "application/json"}
        mock_token_resp.json.return_value = {
            "access_token": "tok",
            "expires_in": 3600,
        }

        mock_http = MagicMock()
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_http.post.side_effect = [mock_register_resp, mock_token_resp]

        with patch("cli.auth.httpx.Client", return_value=mock_http):
            result = login("http://localhost:8088", session_name="dev")

        assert result["agent_name"] == "cli-dev"
        # Verify the registration body had the right agent_name
        reg_call = mock_http.post.call_args_list[0]
        assert reg_call.kwargs["json"]["agent_name"] == "cli-dev"

    def test_login_registration_failure(self, tmp_config_dir):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = {"error": "bad request"}

        mock_http = MagicMock()
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_http.post.return_value = mock_resp

        with (
            patch("cli.auth.httpx.Client", return_value=mock_http),
            pytest.raises(AuthError, match="Registration failed"),
        ):
            login("http://localhost:8088")


class TestGetToken:
    def test_returns_valid_token(self, tmp_config_dir):
        """Valid non-expired token should be returned directly."""
        token_data = {
            "access_token": "valid-tok",
            "expires_at": int(time.time()) + 3600,
        }
        (tmp_config_dir / "token.json").write_text(json.dumps(token_data))

        token = get_token("http://localhost:8088")
        assert token == "valid-tok"

    def test_expired_token_reauths(self, tmp_config_dir):
        """Expired token should trigger re-auth with stored client."""
        token_data = {
            "access_token": "expired-tok",
            "expires_at": int(time.time()) - 100,
        }
        (tmp_config_dir / "token.json").write_text(json.dumps(token_data))

        client_data = {
            "client_id": "cid",
            "client_secret": "sec",
        }
        (tmp_config_dir / "client.json").write_text(json.dumps(client_data))

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "new-tok",
            "expires_in": 3600,
        }
        mock_http = MagicMock()
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_http.post.return_value = mock_resp

        with patch("cli.auth.httpx.Client", return_value=mock_http):
            token = get_token("http://localhost:8088")

        assert token == "new-tok"

    def test_no_client_raises(self, tmp_config_dir):
        """No client file should raise AuthError."""
        with pytest.raises(AuthError, match="Not logged in"):
            get_token("http://localhost:8088")


class TestLogout:
    def test_logout_deletes_files(self, tmp_config_dir):
        (tmp_config_dir / "client.json").write_text("{}")
        (tmp_config_dir / "token.json").write_text("{}")

        logout("http://localhost:8088")

        assert not (tmp_config_dir / "client.json").exists()
        assert not (tmp_config_dir / "token.json").exists()

    def test_logout_no_files_ok(self, tmp_config_dir):
        """Logout when no files exist should not raise."""
        logout("http://localhost:8088")


class TestWhoami:
    def test_whoami_logged_in(self, tmp_config_dir):
        client_data = {
            "client_id": "cid-123",
            "agent_name": "cli",
            "gateway_url": "http://localhost:8088",
        }
        token_data = {
            "access_token": "tok",
            "expires_at": int(time.time()) + 3600,
            "scope": "mcp api",
        }
        (tmp_config_dir / "client.json").write_text(json.dumps(client_data))
        (tmp_config_dir / "token.json").write_text(json.dumps(token_data))

        info = whoami()
        assert info["logged_in"] is True
        assert info["client_id"] == "cid-123"
        assert info["token_valid"] is True

    def test_whoami_not_logged_in(self, tmp_config_dir):
        info = whoami()
        assert info["logged_in"] is False
