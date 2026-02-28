"""Tests for SecretsManager (PostgreSQL backend).

Requires TEST_DATABASE_URL env var pointing to a PostgreSQL instance.
Run: TEST_DATABASE_URL="postgresql://user:pass@host:5432/testdb" pytest tests/unit/test_secrets_manager.py
Skip: pytest -m "not integration"
"""

import os
from unittest.mock import patch

import pytest
from pydantic import SecretStr

DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL not set"),
]


@pytest.fixture(scope="module")
def pg_db():
    """Create a DatabaseManager with sync pool for testing."""
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    from core.database import DatabaseManager

    dm = DatabaseManager(DATABASE_URL)
    dm._sync_pool = ConnectionPool(
        DATABASE_URL,
        min_size=1,
        max_size=3,
        open=False,
        kwargs={"row_factory": dict_row},
    )
    dm._sync_pool.open()

    # Bootstrap schemas
    with dm.acquire_sync() as conn:
        conn.execute("CREATE SCHEMA IF NOT EXISTS vault")
        conn.execute("CREATE SCHEMA IF NOT EXISTS oauth2")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS public._migrations (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                applied_at TIMESTAMPTZ DEFAULT NOW()
            )"""
        )
        conn.commit()

    yield dm

    # Teardown: truncate test data (do NOT drop schema — may be shared with production)
    with dm.acquire_sync() as conn:
        try:
            conn.execute("TRUNCATE vault.secrets CASCADE")
            conn.commit()
        except Exception:
            conn.rollback()

    dm._sync_pool.close()


@pytest.fixture
def tmp_secrets_env(pg_db, tmp_path):
    """Setup secrets environment with key file and clean PG tables."""
    import secrets as stdlib_secrets

    key_path = tmp_path / "config" / "secrets.key"
    key_path.parent.mkdir(parents=True)
    key_data = stdlib_secrets.token_bytes(64)
    key_path.write_bytes(key_data)
    key_path.chmod(0o600)

    # Clean secrets table if it exists
    with pg_db.acquire_sync() as conn:
        row = conn.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'vault' AND table_name = 'secrets'"
        ).fetchone()
        if row:
            conn.execute("TRUNCATE vault.secrets")
        conn.commit()

    with patch("core.registry.get_database", return_value=pg_db):
        yield {
            "key_path": key_path,
            "tmp_path": tmp_path,
            "pg_db": pg_db,
        }


def _make_sm(pg_db, key_path):
    """Helper to create a SecretsManager with patched PG."""
    from ui.secrets_manager import SecretsManager

    with patch("core.registry.get_database", return_value=pg_db):
        return SecretsManager(ssh_key_path=key_path)


class TestSecretsManagerInit:
    """Tests for SecretsManager initialization."""

    def test_finds_key_file(self, tmp_secrets_env):
        """Should find the key file."""
        sm = _make_sm(tmp_secrets_env["pg_db"], tmp_secrets_env["key_path"])

        assert sm.is_available() is True
        assert sm.get_key_source() == str(tmp_secrets_env["key_path"])

    def test_no_key_raises_error(self, pg_db):
        """Should report unavailable when no key found."""
        from ui.secrets_manager import SecretsManager

        with (
            patch("core.registry.get_database", return_value=pg_db),
            patch("ui.secrets_manager.KEY_PATHS", []),
            patch.dict("os.environ", {}, clear=True),
        ):
            sm = SecretsManager()
            assert sm.is_available() is False

    def test_generates_key_file(self, tmp_path):
        """Should generate new key file."""
        from ui.secrets_manager import SecretsManager

        key_path = tmp_path / "new_secrets.key"

        generated = SecretsManager.generate_key_file(key_path)

        assert generated == key_path
        assert key_path.exists()
        assert len(key_path.read_bytes()) == 64
        # Check permissions (0o600)
        assert oct(key_path.stat().st_mode)[-3:] == "600"


class TestEncryptDecrypt:
    """Tests for encryption/decryption."""

    def test_encrypt_decrypt_roundtrip(self, tmp_secrets_env):
        """Should encrypt and decrypt back to original."""
        sm = _make_sm(tmp_secrets_env["pg_db"], tmp_secrets_env["key_path"])

        original = "my-secret-api-key-12345"
        encrypted, nonce = sm._encrypt(original)
        decrypted = sm._decrypt(encrypted, nonce)

        assert decrypted == original
        assert encrypted != original  # Should be different

    def test_different_nonce_each_time(self, tmp_secrets_env):
        """Each encryption should use different nonce."""
        sm = _make_sm(tmp_secrets_env["pg_db"], tmp_secrets_env["key_path"])

        _, nonce1 = sm._encrypt("test")
        _, nonce2 = sm._encrypt("test")

        assert nonce1 != nonce2

    def test_wrong_key_fails_decrypt(self, tmp_secrets_env, tmp_path):
        """Decryption with wrong key should fail."""
        import secrets as stdlib_secrets

        sm1 = _make_sm(tmp_secrets_env["pg_db"], tmp_secrets_env["key_path"])
        encrypted, nonce = sm1._encrypt("secret")

        # Create second manager with different key
        other_key = tmp_path / "other.key"
        other_key.write_bytes(stdlib_secrets.token_bytes(64))

        sm2 = _make_sm(tmp_secrets_env["pg_db"], other_key)

        with pytest.raises(Exception):  # InvalidTag from cryptography
            sm2._decrypt(encrypted, nonce)


class TestSecretsCRUD:
    """Tests for secrets CRUD operations."""

    def test_set_and_get_secret(self, tmp_secrets_env):
        """Should store and retrieve secret as SecretStr."""
        sm = _make_sm(tmp_secrets_env["pg_db"], tmp_secrets_env["key_path"])

        sm.set("API_KEY", "secret-value-123")

        retrieved = sm.get("API_KEY", fallback_env=False)
        assert isinstance(retrieved, SecretStr)
        assert retrieved.get_secret_value() == "secret-value-123"
        assert str(retrieved) == "**********"  # Never leaks in logs

    def test_get_nonexistent_returns_none(self, tmp_secrets_env):
        """Should return None for nonexistent secret."""
        sm = _make_sm(tmp_secrets_env["pg_db"], tmp_secrets_env["key_path"])

        result = sm.get("NONEXISTENT", fallback_env=False)
        assert result is None

    def test_get_fallback_to_env(self, tmp_secrets_env):
        """Should fallback to environment variable as SecretStr."""
        sm = _make_sm(tmp_secrets_env["pg_db"], tmp_secrets_env["key_path"])

        with patch.dict("os.environ", {"MY_ENV_VAR": "env-value"}):
            result = sm.get("MY_ENV_VAR", fallback_env=True)
            assert isinstance(result, SecretStr)
            assert result.get_secret_value() == "env-value"

    def test_update_existing_secret(self, tmp_secrets_env):
        """Should update existing secret."""
        sm = _make_sm(tmp_secrets_env["pg_db"], tmp_secrets_env["key_path"])

        sm.set("KEY", "value1")
        sm.set("KEY", "value2")

        assert sm.get("KEY", fallback_env=False).get_secret_value() == "value2"

    def test_get_plain_returns_str(self, tmp_secrets_env):
        """get_plain() should return plain str, not SecretStr."""
        sm = _make_sm(tmp_secrets_env["pg_db"], tmp_secrets_env["key_path"])

        sm.set("PLAIN_KEY", "plain-value")

        result = sm.get_plain("PLAIN_KEY", fallback_env=False)
        assert isinstance(result, str)
        assert not isinstance(result, SecretStr)
        assert result == "plain-value"

    def test_get_plain_returns_default_when_missing(self, tmp_secrets_env):
        """get_plain() should return default when secret not found."""
        sm = _make_sm(tmp_secrets_env["pg_db"], tmp_secrets_env["key_path"])

        result = sm.get_plain("NONEXISTENT", fallback_env=False)
        assert result == ""

        result = sm.get_plain("NONEXISTENT", fallback_env=False, default="fallback")
        assert result == "fallback"

    def test_delete_secret(self, tmp_secrets_env):
        """Should delete secret."""
        sm = _make_sm(tmp_secrets_env["pg_db"], tmp_secrets_env["key_path"])

        sm.set("TO_DELETE", "value")
        assert sm.exists("TO_DELETE") is True

        deleted = sm.delete("TO_DELETE")

        assert deleted is True
        assert sm.exists("TO_DELETE") is False

    def test_delete_nonexistent_returns_false(self, tmp_secrets_env):
        """Should return False when deleting nonexistent."""
        sm = _make_sm(tmp_secrets_env["pg_db"], tmp_secrets_env["key_path"])

        deleted = sm.delete("NONEXISTENT")
        assert deleted is False

    def test_exists(self, tmp_secrets_env):
        """Should check if secret exists."""
        sm = _make_sm(tmp_secrets_env["pg_db"], tmp_secrets_env["key_path"])

        assert sm.exists("KEY") is False
        sm.set("KEY", "value")
        assert sm.exists("KEY") is True

    def test_list_keys(self, tmp_secrets_env):
        """Should list all secret keys without values."""
        sm = _make_sm(tmp_secrets_env["pg_db"], tmp_secrets_env["key_path"])

        sm.set("KEY_A", "value_a", description="Description A")
        sm.set("KEY_B", "value_b")

        keys = sm.list_keys()

        assert len(keys) == 2
        key_names = [k["key_name"] for k in keys]
        assert "KEY_A" in key_names
        assert "KEY_B" in key_names

        # Should have description
        key_a = next(k for k in keys if k["key_name"] == "KEY_A")
        assert key_a["description"] == "Description A"


class TestSecretsExportImport:
    """Tests for export/import functionality."""

    def test_export_all(self, tmp_secrets_env):
        """Should export all secrets as dict."""
        sm = _make_sm(tmp_secrets_env["pg_db"], tmp_secrets_env["key_path"])

        sm.set("KEY1", "value1", description="Desc 1")
        sm.set("KEY2", "value2")

        exported = sm.export_all()

        assert "secrets" in exported
        assert "exported_at" in exported
        assert len(exported["secrets"]) == 2

        # Values should be plaintext
        key1 = next(s for s in exported["secrets"] if s["key"] == "KEY1")
        assert key1["value"] == "value1"

    def test_import_all(self, tmp_secrets_env):
        """Should import secrets from dict."""
        sm = _make_sm(tmp_secrets_env["pg_db"], tmp_secrets_env["key_path"])

        data = {
            "secrets": [
                {"key": "IMPORTED1", "value": "val1", "description": "Imported"},
                {"key": "IMPORTED2", "value": "val2"},
            ]
        }

        results = sm.import_all(data)

        assert results["IMPORTED1"] is True
        assert results["IMPORTED2"] is True
        assert sm.get_plain("IMPORTED1", fallback_env=False) == "val1"
        assert sm.get_plain("IMPORTED2", fallback_env=False) == "val2"

    def test_import_no_overwrite(self, tmp_secrets_env):
        """Should not overwrite when overwrite=False."""
        sm = _make_sm(tmp_secrets_env["pg_db"], tmp_secrets_env["key_path"])

        sm.set("EXISTING", "original")

        data = {"secrets": [{"key": "EXISTING", "value": "new"}]}
        results = sm.import_all(data, overwrite=False)

        assert results["EXISTING"] is False
        assert sm.get_plain("EXISTING", fallback_env=False) == "original"

    def test_export_import_roundtrip(self, tmp_secrets_env):
        """Should export and import without data loss."""
        sm = _make_sm(tmp_secrets_env["pg_db"], tmp_secrets_env["key_path"])

        sm.set("SECRET1", "value1")
        sm.set("SECRET2", "value2")

        exported = sm.export_all()

        # Clear secrets to simulate a fresh import
        with tmp_secrets_env["pg_db"].acquire_sync() as conn:
            conn.execute("TRUNCATE vault.secrets")
            conn.commit()

        # Import into same PG (different sm instance, same key)
        sm2 = _make_sm(tmp_secrets_env["pg_db"], tmp_secrets_env["key_path"])
        sm2.import_all(exported)

        assert sm2.get_plain("SECRET1", fallback_env=False) == "value1"
        assert sm2.get_plain("SECRET2", fallback_env=False) == "value2"


class TestSecretsImportFromEnv:
    """Tests for importing from environment variables."""

    def test_import_from_env(self, tmp_secrets_env):
        """Should import secrets from environment."""
        sm = _make_sm(tmp_secrets_env["pg_db"], tmp_secrets_env["key_path"])

        with patch.dict(
            "os.environ",
            {
                "ENV_KEY1": "env_value1",
                "ENV_KEY2": "env_value2",
            },
        ):
            results = sm.import_from_env(["ENV_KEY1", "ENV_KEY2", "MISSING"])

        assert results["ENV_KEY1"] is True
        assert results["ENV_KEY2"] is True
        assert results["MISSING"] is False

        assert sm.get_plain("ENV_KEY1", fallback_env=False) == "env_value1"

    def test_import_from_env_no_overwrite(self, tmp_secrets_env):
        """Should not overwrite existing when importing from env."""
        sm = _make_sm(tmp_secrets_env["pg_db"], tmp_secrets_env["key_path"])

        sm.set("EXISTING", "db_value")

        with patch.dict("os.environ", {"EXISTING": "env_value"}):
            results = sm.import_from_env(["EXISTING"], overwrite=False)

        assert results["EXISTING"] is False
        assert sm.get_plain("EXISTING", fallback_env=False) == "db_value"
