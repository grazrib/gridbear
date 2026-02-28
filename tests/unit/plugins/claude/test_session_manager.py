"""Tests for Claude SessionManager."""

from datetime import datetime, timedelta

import pytest

from plugins.claude.session_manager import ClaudeSession, SessionManager


class TestClaudeSession:
    """Tests for the ClaudeSession dataclass."""

    def test_defaults(self):
        now = datetime.now()
        session = ClaudeSession(
            session_id="abc",
            agent_id="myagent",
            created_at=now,
            last_activity=now,
        )
        assert session.history == []
        assert session.total_tokens == 0
        assert session.total_cost_usd == 0.0


class TestSessionManagerGetOrCreate:
    """Tests for get_or_create()."""

    def test_create_new_session(self):
        mgr = SessionManager()
        session = mgr.get_or_create(None, "myagent")
        assert session.agent_id == "myagent"
        assert session.session_id
        assert mgr.session_count == 1

    def test_return_existing_session(self):
        mgr = SessionManager()
        s1 = mgr.get_or_create(None, "myagent")
        s2 = mgr.get_or_create(s1.session_id, "myagent")
        assert s1.session_id == s2.session_id
        assert mgr.session_count == 1

    def test_unknown_session_id_creates_new(self):
        mgr = SessionManager()
        session = mgr.get_or_create("nonexistent-id", "myagent")
        assert session.session_id != "nonexistent-id"
        assert mgr.session_count == 1

    def test_updates_last_activity(self):
        mgr = SessionManager()
        s1 = mgr.get_or_create(None, "myagent")
        old_activity = s1.last_activity
        s1.last_activity = datetime.now() - timedelta(seconds=10)
        s2 = mgr.get_or_create(s1.session_id, "myagent")
        assert s2.last_activity > old_activity - timedelta(seconds=10)

    def test_max_sessions_raises(self):
        mgr = SessionManager()
        mgr.MAX_SESSIONS = 3
        mgr.get_or_create(None, "a1")
        mgr.get_or_create(None, "a2")
        mgr.get_or_create(None, "a3")
        with pytest.raises(ValueError, match="Maximum sessions"):
            mgr.get_or_create(None, "a4")

    def test_max_sessions_reclaims_expired(self):
        mgr = SessionManager(ttl_hours=1)
        mgr.MAX_SESSIONS = 2
        s1 = mgr.get_or_create(None, "a1")
        s1.last_activity = datetime.now() - timedelta(hours=2)
        mgr.get_or_create(None, "a2")
        s3 = mgr.get_or_create(None, "a3")
        assert s3.agent_id == "a3"
        assert mgr.session_count == 2


class TestSessionManagerAppendTurn:
    """Tests for append_turn()."""

    def test_append_user_turn(self):
        mgr = SessionManager()
        session = mgr.get_or_create(None, "myagent")
        mgr.append_turn(session.session_id, "user", "Hello")
        history = mgr.get_history(session.session_id)
        assert len(history) == 1
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "Hello"

    def test_append_assistant_turn(self):
        mgr = SessionManager()
        session = mgr.get_or_create(None, "myagent")
        mgr.append_turn(session.session_id, "assistant", "Hi there!")
        history = mgr.get_history(session.session_id)
        assert len(history) == 1
        assert history[0]["role"] == "assistant"
        assert history[0]["content"] == "Hi there!"

    def test_sliding_window(self):
        mgr = SessionManager()
        mgr.MAX_HISTORY_TURNS = 5
        session = mgr.get_or_create(None, "myagent")
        for i in range(10):
            mgr.append_turn(session.session_id, "user", f"msg-{i}")
        history = mgr.get_history(session.session_id)
        assert len(history) == 5
        assert history[0]["content"] == "msg-5"
        assert history[-1]["content"] == "msg-9"

    def test_append_to_unknown_session(self):
        """Appending to nonexistent session is a no-op."""
        mgr = SessionManager()
        mgr.append_turn("nonexistent", "user", "Hello")
        assert mgr.get_history("nonexistent") == []


class TestSessionManagerUsage:
    """Tests for update_usage()."""

    def test_accumulates_tokens(self):
        mgr = SessionManager()
        session = mgr.get_or_create(None, "myagent")
        sid = session.session_id
        mgr.update_usage(sid, 100, 50, 0.01)
        mgr.update_usage(sid, 200, 100, 0.02)
        assert session.total_tokens == 450
        assert session.total_cost_usd == pytest.approx(0.03)

    def test_unknown_session_no_error(self):
        mgr = SessionManager()
        mgr.update_usage("nonexistent", 100, 50, 0.01)


class TestSessionManagerCleanup:
    """Tests for cleanup_expired()."""

    def test_removes_expired_sessions(self):
        mgr = SessionManager(ttl_hours=1)
        s1 = mgr.get_or_create(None, "a1")
        s2 = mgr.get_or_create(None, "a2")
        s1.last_activity = datetime.now() - timedelta(hours=2)
        removed = mgr.cleanup_expired()
        assert removed == 1
        assert mgr.session_count == 1
        assert mgr.get_history(s2.session_id) is not None

    def test_keeps_active_sessions(self):
        mgr = SessionManager(ttl_hours=1)
        mgr.get_or_create(None, "a1")
        removed = mgr.cleanup_expired()
        assert removed == 0
        assert mgr.session_count == 1

    def test_cleanup_all_expired(self):
        mgr = SessionManager(ttl_hours=0)
        s1 = mgr.get_or_create(None, "a1")
        s2 = mgr.get_or_create(None, "a2")
        s1.last_activity = datetime.now() - timedelta(hours=1)
        s2.last_activity = datetime.now() - timedelta(hours=1)
        removed = mgr.cleanup_expired()
        assert removed == 2
        assert mgr.session_count == 0


class TestSessionManagerCleanupLoop:
    """Tests for the async cleanup loop."""

    async def test_start_stop_cleanup_loop(self):
        mgr = SessionManager()
        await mgr.start_cleanup_loop(interval_minutes=60)
        assert mgr._cleanup_task is not None
        await mgr.stop_cleanup_loop()
        assert mgr._cleanup_task is None

    async def test_stop_without_start(self):
        """Stop without start is a no-op."""
        mgr = SessionManager()
        await mgr.stop_cleanup_loop()
        assert mgr._cleanup_task is None
