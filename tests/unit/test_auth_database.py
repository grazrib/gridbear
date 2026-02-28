"""Tests for AuthDatabase (PostgreSQL backend).

Requires TEST_DATABASE_URL env var pointing to a PostgreSQL instance.
Run: TEST_DATABASE_URL="postgresql://user:pass@host:5432/testdb" pytest tests/unit/test_auth_database.py
Skip: pytest -m "not integration"
"""

import os
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL not set"),
]


@pytest.fixture(scope="module")
def pg_db():
    """Create a DatabaseManager with sync pool only (no async needed)."""
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

    # Bootstrap: ensure admin schema and _migrations table exist
    with dm.acquire_sync() as conn:
        conn.execute("CREATE SCHEMA IF NOT EXISTS admin")
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
        for table in (
            "admin.user_tool_preferences",
            "admin.webauthn_credentials",
            "admin.audit_log",
            "admin.sessions",
            "admin.recovery_codes",
            "admin.users",
        ):
            try:
                conn.execute(f"TRUNCATE {table} CASCADE")
            except Exception:
                conn.rollback()
                break
        else:
            conn.commit()

    dm._sync_pool.close()


@pytest.fixture
def tmp_auth_db(pg_db):
    """Create an AuthDatabase instance with clean tables per test."""
    import ui.auth.database as auth_db_module

    # Reset singleton from previous tests
    auth_db_module.reset_auth_db()

    # Truncate tables if they exist (for test isolation)
    with pg_db.acquire_sync() as conn:
        row = conn.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'admin' AND table_name = 'users'"
        ).fetchone()
        if row:
            conn.execute("TRUNCATE admin.audit_log CASCADE")
            conn.execute("TRUNCATE admin.webauthn_credentials CASCADE")
            conn.execute("TRUNCATE admin.user_tool_preferences CASCADE")
            conn.execute("TRUNCATE admin.sessions CASCADE")
            conn.execute("TRUNCATE admin.recovery_codes CASCADE")
            conn.execute("TRUNCATE admin.users CASCADE")
        conn.commit()

    # Patch get_database so AuthDatabase.__init__ uses our test pool
    with patch("core.registry.get_database", return_value=pg_db):
        db = auth_db_module.AuthDatabase()

    yield db

    auth_db_module.reset_auth_db()


class TestAuthDatabaseInit:
    """Tests for AuthDatabase initialization."""

    def test_creates_tables(self, tmp_auth_db):
        """Should create all required tables in the admin schema."""
        db = tmp_auth_db

        with db._db.acquire_sync() as conn:
            rows = conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'admin' ORDER BY table_name"
            ).fetchall()
            tables = [row["table_name"] for row in rows]

        assert "users" in tables
        assert "recovery_codes" in tables
        assert "sessions" in tables
        assert "audit_log" in tables
        assert "webauthn_credentials" in tables
        assert "user_tool_preferences" in tables


class TestUserOperations:
    """Tests for user CRUD operations."""

    def test_create_user(self, tmp_auth_db):
        """Should create a new user."""
        db = tmp_auth_db

        user_id = db.create_user(
            username="testadmin",
            password_hash="hashed_password_123",
            email="test@example.com",
        )

        assert user_id > 0

        user = db.get_user_by_id(user_id)
        assert user["username"] == "testadmin"
        assert user["email"] == "test@example.com"

    def test_username_normalized_lowercase(self, tmp_auth_db):
        """Should normalize username to lowercase."""
        db = tmp_auth_db
        db.create_user(username="TestAdmin", password_hash="hash")

        user = db.get_user_by_username("TESTADMIN")
        assert user is not None
        assert user["username"] == "testadmin"

    def test_create_superadmin(self, tmp_auth_db):
        """Should create superadmin user."""
        db = tmp_auth_db
        user_id = db.create_user(
            username="superuser", password_hash="hash", is_superadmin=True
        )

        user = db.get_user_by_id(user_id)
        assert user["is_superadmin"] is True

    def test_get_user_by_username_not_found(self, tmp_auth_db):
        """Should return None for nonexistent user."""
        db = tmp_auth_db
        user = db.get_user_by_username("nonexistent")
        assert user is None

    def test_get_all_users(self, tmp_auth_db):
        """Should return all users."""
        db = tmp_auth_db
        db.create_user(username="user1", password_hash="h1")
        db.create_user(username="user2", password_hash="h2")

        users = db.get_all_users()

        assert len(users) == 2
        usernames = [u["username"] for u in users]
        assert "user1" in usernames
        assert "user2" in usernames

    def test_user_count(self, tmp_auth_db):
        """Should return correct user count."""
        db = tmp_auth_db
        assert db.user_count() == 0

        db.create_user(username="user1", password_hash="h")
        assert db.user_count() == 1

        db.create_user(username="user2", password_hash="h")
        assert db.user_count() == 2

    def test_update_user(self, tmp_auth_db):
        """Should update user fields."""
        db = tmp_auth_db
        user_id = db.create_user(username="user", password_hash="old_hash")

        updated = db.update_user(
            user_id, password_hash="new_hash", email="new@email.com"
        )

        assert updated is True
        user = db.get_user_by_id(user_id)
        assert user["password_hash"] == "new_hash"
        assert user["email"] == "new@email.com"

    def test_update_user_invalid_field_ignored(self, tmp_auth_db):
        """Should ignore invalid fields."""
        db = tmp_auth_db
        user_id = db.create_user(username="user", password_hash="hash")

        # Should not raise, just ignore invalid field
        updated = db.update_user(user_id, invalid_field="value")
        assert updated is False

    def test_delete_user(self, tmp_auth_db):
        """Should delete user."""
        db = tmp_auth_db
        user_id = db.create_user(username="todelete", password_hash="h")

        deleted = db.delete_user(user_id)

        assert deleted is True
        assert db.get_user_by_id(user_id) is None


class TestFailedLoginAttempts:
    """Tests for login attempt tracking."""

    def test_increment_failed_attempts(self, tmp_auth_db):
        """Should increment failed attempts."""
        db = tmp_auth_db
        user_id = db.create_user(username="user", password_hash="h")

        count = db.increment_failed_attempts(user_id)
        assert count == 1

        count = db.increment_failed_attempts(user_id)
        assert count == 2

    def test_reset_failed_attempts(self, tmp_auth_db):
        """Should reset failed attempts to zero."""
        db = tmp_auth_db
        user_id = db.create_user(username="user", password_hash="h")

        db.increment_failed_attempts(user_id)
        db.increment_failed_attempts(user_id)
        db.reset_failed_attempts(user_id)

        user = db.get_user_by_id(user_id)
        assert user["failed_login_attempts"] == 0

    def test_set_lockout(self, tmp_auth_db):
        """Should set lockout time."""
        db = tmp_auth_db
        user_id = db.create_user(username="user", password_hash="h")

        lockout_time = datetime.now() + timedelta(minutes=30)
        db.set_lockout(user_id, lockout_time)

        assert db.is_locked_out(user_id) is True

    def test_lockout_expired(self, tmp_auth_db):
        """Should not be locked out after expiry."""
        db = tmp_auth_db
        user_id = db.create_user(username="user", password_hash="h")

        # Set lockout in the past
        lockout_time = datetime.now() - timedelta(minutes=1)
        db.set_lockout(user_id, lockout_time)

        assert db.is_locked_out(user_id) is False


class TestRecoveryCodes:
    """Tests for recovery code operations."""

    def test_add_recovery_codes(self, tmp_auth_db):
        """Should add recovery codes."""
        db = tmp_auth_db
        user_id = db.create_user(username="user", password_hash="h")

        code_hashes = ["hash1", "hash2", "hash3"]
        db.add_recovery_codes(user_id, code_hashes)

        codes = db.get_recovery_codes(user_id)
        assert len(codes) == 3

    def test_add_recovery_codes_replaces_existing(self, tmp_auth_db):
        """Should replace existing codes when adding new ones."""
        db = tmp_auth_db
        user_id = db.create_user(username="user", password_hash="h")

        db.add_recovery_codes(user_id, ["old1", "old2"])
        db.add_recovery_codes(user_id, ["new1"])

        codes = db.get_recovery_codes(user_id)
        assert len(codes) == 1
        assert codes[0]["code_hash"] == "new1"

    def test_get_unused_recovery_codes(self, tmp_auth_db):
        """Should only return unused codes."""
        db = tmp_auth_db
        user_id = db.create_user(username="user", password_hash="h")

        db.add_recovery_codes(user_id, ["code1", "code2", "code3"])

        # Mark one as used
        codes = db.get_recovery_codes(user_id)
        db.mark_recovery_code_used(codes[0]["id"])

        unused = db.get_unused_recovery_codes(user_id)
        assert len(unused) == 2

    def test_mark_recovery_code_used(self, tmp_auth_db):
        """Should mark code as used with timestamp."""
        db = tmp_auth_db
        user_id = db.create_user(username="user", password_hash="h")

        db.add_recovery_codes(user_id, ["testcode"])
        codes = db.get_recovery_codes(user_id)
        code_id = codes[0]["id"]

        marked = db.mark_recovery_code_used(code_id)

        assert marked is True

        codes = db.get_recovery_codes(user_id)
        assert codes[0]["used_at"] is not None

    def test_mark_already_used_code_fails(self, tmp_auth_db):
        """Should not re-mark already used code."""
        db = tmp_auth_db
        user_id = db.create_user(username="user", password_hash="h")

        db.add_recovery_codes(user_id, ["testcode"])
        codes = db.get_recovery_codes(user_id)
        code_id = codes[0]["id"]

        db.mark_recovery_code_used(code_id)
        marked_again = db.mark_recovery_code_used(code_id)

        assert marked_again is False


class TestSessionOperations:
    """Tests for session management."""

    def test_create_session(self, tmp_auth_db):
        """Should create a session."""
        db = tmp_auth_db
        user_id = db.create_user(username="user", password_hash="h")

        expires = datetime.now() + timedelta(hours=24)
        session_id = db.create_session(
            session_token="token123",
            user_id=user_id,
            expires_at=expires,
            ip_address="127.0.0.1",
            user_agent="Mozilla/5.0",
        )

        assert session_id > 0

        session = db.get_session("token123")
        assert session["user_id"] == user_id
        assert session["ip_address"] == "127.0.0.1"

    def test_get_session_not_found(self, tmp_auth_db):
        """Should return None for nonexistent session."""
        db = tmp_auth_db
        session = db.get_session("nonexistent")
        assert session is None

    def test_get_user_sessions(self, tmp_auth_db):
        """Should get all sessions for a user."""
        db = tmp_auth_db
        user_id = db.create_user(username="user", password_hash="h")

        expires = datetime.now() + timedelta(hours=24)
        db.create_session("token1", user_id, expires)
        db.create_session("token2", user_id, expires)

        sessions = db.get_user_sessions(user_id)
        assert len(sessions) == 2

    def test_update_session_activity(self, tmp_auth_db):
        """Should update last activity timestamp."""
        db = tmp_auth_db
        user_id = db.create_user(username="user", password_hash="h")

        expires = datetime.now() + timedelta(hours=24)
        db.create_session("token", user_id, expires)

        updated = db.update_session_activity("token")
        assert updated is True

    def test_delete_session(self, tmp_auth_db):
        """Should delete a session."""
        db = tmp_auth_db
        user_id = db.create_user(username="user", password_hash="h")

        expires = datetime.now() + timedelta(hours=24)
        db.create_session("token", user_id, expires)

        deleted = db.delete_session("token")

        assert deleted is True
        assert db.get_session("token") is None

    def test_delete_user_sessions(self, tmp_auth_db):
        """Should delete all user sessions."""
        db = tmp_auth_db
        user_id = db.create_user(username="user", password_hash="h")

        expires = datetime.now() + timedelta(hours=24)
        db.create_session("token1", user_id, expires)
        db.create_session("token2", user_id, expires)

        deleted_count = db.delete_user_sessions(user_id)

        assert deleted_count == 2
        assert len(db.get_user_sessions(user_id)) == 0

    def test_delete_user_sessions_except_one(self, tmp_auth_db):
        """Should keep specified session when deleting others."""
        db = tmp_auth_db
        user_id = db.create_user(username="user", password_hash="h")

        expires = datetime.now() + timedelta(hours=24)
        db.create_session("keep_this", user_id, expires)
        db.create_session("delete_this", user_id, expires)

        deleted_count = db.delete_user_sessions(user_id, except_token="keep_this")

        assert deleted_count == 1
        assert db.get_session("keep_this") is not None
        assert db.get_session("delete_this") is None

    def test_cleanup_expired_sessions(self, tmp_auth_db):
        """Should delete expired sessions."""
        db = tmp_auth_db
        user_id = db.create_user(username="user", password_hash="h")

        # Create expired session
        expired = datetime.now() - timedelta(hours=1)
        db.create_session("expired", user_id, expired)

        # Create valid session
        valid = datetime.now() + timedelta(hours=24)
        db.create_session("valid", user_id, valid)

        deleted = db.cleanup_expired_sessions()

        assert deleted == 1
        assert db.get_session("expired") is None
        assert db.get_session("valid") is not None


class TestAuditLog:
    """Tests for audit log operations."""

    def test_log_event(self, tmp_auth_db):
        """Should log an event."""
        db = tmp_auth_db
        user_id = db.create_user(username="user", password_hash="h")

        log_id = db.log_event(
            event_type="LOGIN",
            user_id=user_id,
            username="user",
            ip_address="127.0.0.1",
            success=True,
            details="Successful login",
        )

        assert log_id > 0

    def test_get_audit_logs(self, tmp_auth_db):
        """Should retrieve audit logs."""
        db = tmp_auth_db
        user_id = db.create_user(username="user", password_hash="h")

        db.log_event("LOGIN", user_id=user_id, success=True)
        db.log_event("LOGOUT", user_id=user_id, success=True)

        logs = db.get_audit_logs()

        assert len(logs) == 2

    def test_get_audit_logs_filtered_by_user(self, tmp_auth_db):
        """Should filter logs by user."""
        db = tmp_auth_db
        user1_id = db.create_user(username="user1", password_hash="h")
        user2_id = db.create_user(username="user2", password_hash="h")

        db.log_event("LOGIN", user_id=user1_id, success=True)
        db.log_event("LOGIN", user_id=user2_id, success=True)
        db.log_event("LOGOUT", user_id=user1_id, success=True)

        logs = db.get_audit_logs(user_id=user1_id)

        assert len(logs) == 2

    def test_get_audit_logs_filtered_by_event_type(self, tmp_auth_db):
        """Should filter logs by event type."""
        db = tmp_auth_db

        db.log_event("LOGIN", success=True)
        db.log_event("LOGIN", success=False)
        db.log_event("LOGOUT", success=True)

        logs = db.get_audit_logs(event_type="LOGIN")

        assert len(logs) == 2

    def test_get_audit_logs_with_limit_offset(self, tmp_auth_db):
        """Should support pagination."""
        db = tmp_auth_db

        for i in range(10):
            db.log_event(f"EVENT_{i}", success=True)

        page1 = db.get_audit_logs(limit=3, offset=0)
        page2 = db.get_audit_logs(limit=3, offset=3)

        assert len(page1) == 3
        assert len(page2) == 3
        assert page1[0]["id"] != page2[0]["id"]

    def test_cleanup_old_audit_logs(self, tmp_auth_db):
        """Should delete old audit logs."""
        db = tmp_auth_db

        # Insert old log directly via PG
        old_date = datetime.now() - timedelta(days=100)
        with db._db.acquire_sync() as conn:
            conn.execute(
                "INSERT INTO admin.audit_log (event_type, success, created_at) "
                "VALUES (%s, %s, %s)",
                ("OLD_EVENT", True, old_date),
            )
            conn.commit()

        # Insert recent log via API
        db.log_event("RECENT_EVENT", success=True)

        deleted = db.cleanup_old_audit_logs(days=90)

        assert deleted == 1

        logs = db.get_audit_logs()
        assert len(logs) == 1
        assert logs[0]["event_type"] == "RECENT_EVENT"
