"""Tests for runner auth error tracking, auth status augmentation,
and secrets-manager credential helpers."""

import json
import time

import pytest
from pydantic import SecretStr

import plugins.claude.runner as runner_module
from plugins.claude.runner import get_auth_error_info


@pytest.fixture(autouse=True)
def _reset_auth_error():
    """Reset the module-level auth error timestamp between tests."""
    runner_module._last_auth_error_at = 0.0
    yield
    runner_module._last_auth_error_at = 0.0


class TestGetAuthErrorInfo:
    """Test the get_auth_error_info() accessor."""

    def test_returns_none_when_no_error(self):
        assert get_auth_error_info() is None

    def test_returns_info_after_recent_error(self):
        runner_module._last_auth_error_at = time.time()
        info = get_auth_error_info()
        assert info is not None
        assert "timestamp" in info

    def test_returns_none_when_error_older_than_1h(self):
        runner_module._last_auth_error_at = time.time() - 3601
        assert get_auth_error_info() is None

    def test_returns_info_at_boundary(self):
        # Just under 1 hour should still return info
        runner_module._last_auth_error_at = time.time() - 3599
        assert get_auth_error_info() is not None


class TestNotifyAuthFailureSetsTimestamp:
    """Test that _notify_auth_failure() sets the timestamp."""

    def test_sets_timestamp(self, monkeypatch):
        import sys
        import types

        # Mock core.notifications_client (httpx not available in test env)
        mock_mod = types.ModuleType("core.notifications_client")

        async def _noop(**kw):
            pass

        mock_mod.send_notification = _noop
        monkeypatch.setitem(sys.modules, "core.notifications_client", mock_mod)
        # Swallow the coroutine to avoid "never awaited" warning
        monkeypatch.setattr("asyncio.ensure_future", lambda coro: coro.close())

        from plugins.claude.runner import ClaudeRunner

        runner = ClaudeRunner({"model": "sonnet"})

        assert runner_module._last_auth_error_at == 0.0
        runner._notify_auth_failure()
        assert runner_module._last_auth_error_at > 0.0
        assert get_auth_error_info() is not None


class TestAuthStatusAugmentation:
    """Test that auth_status endpoint augments response with token_expired."""

    def test_augments_when_logged_in_and_error(self, monkeypatch):
        """Simulate what auth_status does: check runner flag on a loggedIn status."""
        runner_module._last_auth_error_at = time.time()

        # Replicate the augmentation logic from routes.py
        status = {"loggedIn": True, "email": "test@example.com"}
        auth_error = get_auth_error_info()
        if status.get("loggedIn") and auth_error:
            status["token_expired"] = True
            status["token_error_message"] = (
                "Token expired or invalid — last failure at runtime. "
                "Re-authenticate to fix."
            )

        assert status["token_expired"] is True
        assert "token_error_message" in status

    def test_no_augmentation_when_not_logged_in(self):
        """Should not add token_expired when loggedIn is False."""
        runner_module._last_auth_error_at = time.time()

        status = {"loggedIn": False}
        auth_error = get_auth_error_info()
        if status.get("loggedIn") and auth_error:
            status["token_expired"] = True

        assert "token_expired" not in status

    def test_no_augmentation_when_no_error(self):
        """Should not add token_expired when no auth error recorded."""
        status = {"loggedIn": True, "email": "test@example.com"}
        auth_error = get_auth_error_info()
        if status.get("loggedIn") and auth_error:
            status["token_expired"] = True

        assert "token_expired" not in status


class TestSecretsManagerHelpers:
    """Test _save/_read/_clear credentials helpers (mocked secrets_manager)."""

    _SAMPLE_OAUTH = {
        "accessToken": "my-token-abc",
        "refreshToken": "my-refresh",
        "expiresAt": 12345,
        "scopes": ["user:inference"],
    }

    def test_save_and_read_roundtrip(self, monkeypatch):
        """OAuth block stored via _save should be readable via _read."""
        store = {}

        def mock_set(key, value, description=None):
            store[key] = value

        def mock_get(key, fallback_env=True):
            val = store.get(key)
            return SecretStr(val) if val is not None else None

        monkeypatch.setattr("plugins.claude.api.routes.secrets_manager.set", mock_set)
        monkeypatch.setattr("plugins.claude.api.routes.secrets_manager.get", mock_get)

        from plugins.claude.api.routes import (
            _read_credentials_from_secrets,
            _save_credentials_to_secrets,
        )

        assert _read_credentials_from_secrets() is None
        _save_credentials_to_secrets(self._SAMPLE_OAUTH)
        result = _read_credentials_from_secrets()
        assert result["accessToken"] == "my-token-abc"
        assert result["refreshToken"] == "my-refresh"

    def test_clear_removes_credentials(self, monkeypatch):
        """_clear should remove credentials from the store."""
        store = {"CLAUDE_CLI_CREDENTIALS": json.dumps(self._SAMPLE_OAUTH)}

        def mock_delete(key):
            store.pop(key, None)
            return True

        def mock_get(key, fallback_env=True):
            val = store.get(key)
            return SecretStr(val) if val is not None else None

        monkeypatch.setattr(
            "plugins.claude.api.routes.secrets_manager.delete", mock_delete
        )
        monkeypatch.setattr("plugins.claude.api.routes.secrets_manager.get", mock_get)

        from plugins.claude.api.routes import (
            _clear_credentials_from_secrets,
            _read_credentials_from_secrets,
        )

        assert _read_credentials_from_secrets() is not None
        _clear_credentials_from_secrets()
        assert _read_credentials_from_secrets() is None


class TestGetCliEnv:
    """Test _get_cli_env() injects CLAUDE_CODE_OAUTH_TOKEN from secrets."""

    def test_includes_token_when_present(self, monkeypatch):
        oauth = {"accessToken": "env-token-xyz", "refreshToken": "", "expiresAt": 0}
        monkeypatch.setattr(
            "plugins.claude.api.routes.secrets_manager.get",
            lambda key, fallback_env=True: (
                SecretStr(json.dumps(oauth))
                if key == "CLAUDE_CLI_CREDENTIALS"
                else None
            ),
        )

        from plugins.claude.api.routes import _get_cli_env

        env = _get_cli_env()
        assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "env-token-xyz"
        assert env["HOME"] == "/home/gridbear"

    def test_no_token_when_secrets_empty(self, monkeypatch):
        monkeypatch.setattr(
            "plugins.claude.api.routes.secrets_manager.get",
            lambda key, fallback_env=True: None,
        )

        from plugins.claude.api.routes import _get_cli_env

        env = _get_cli_env()
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in env
        assert env["HOME"] == "/home/gridbear"


class TestProcessPoolGetOauthToken:
    """Test ClaudeProcessPool._get_oauth_token()."""

    _SAMPLE_OAUTH = {
        "accessToken": "pool-token-123",
        "refreshToken": "pool-refresh",
        "expiresAt": 99999,
        "scopes": ["user:inference"],
    }

    def test_returns_token_when_present(self, monkeypatch):
        monkeypatch.setattr(
            "plugins.claude.api.routes.secrets_manager.get",
            lambda key, fallback_env=True: (
                SecretStr(json.dumps(self._SAMPLE_OAUTH))
                if key == "CLAUDE_CLI_CREDENTIALS"
                else None
            ),
        )

        from plugins.claude.process_pool import ClaudeProcessPool

        token = ClaudeProcessPool._get_oauth_token()
        assert token == "pool-token-123"

    def test_returns_none_when_no_credentials(self, monkeypatch):
        monkeypatch.setattr(
            "plugins.claude.api.routes.secrets_manager.get",
            lambda key, fallback_env=True: None,
        )

        from plugins.claude.process_pool import ClaudeProcessPool

        assert ClaudeProcessPool._get_oauth_token() is None

    def test_handles_error_gracefully(self, monkeypatch):
        def _raise(*a, **kw):
            raise RuntimeError("DB not ready")

        monkeypatch.setattr("plugins.claude.api.routes.secrets_manager.get", _raise)

        from plugins.claude.process_pool import ClaudeProcessPool

        # Should not raise
        assert ClaudeProcessPool._get_oauth_token() is None
