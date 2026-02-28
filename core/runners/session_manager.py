"""Base session manager for runner plugins.

Provides ``RunnerSession`` (dataclass) and ``BaseSessionManager`` with all
lifecycle methods.  Each runner subclass only needs to set ``_log_prefix``
and, if the wire format differs, override ``_format_turn()``.
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from config.logging_config import logger


@dataclass
class RunnerSession:
    """In-memory session state shared by all runners."""

    session_id: str
    agent_id: str
    created_at: datetime
    last_activity: datetime
    history: list[dict] = field(default_factory=list)
    total_tokens: int = 0
    total_cost_usd: float = 0.0


class BaseSessionManager:
    """Shared session lifecycle: create, append, expire, cleanup.

    Subclasses set ``_log_prefix`` (e.g. ``"Claude"``) and optionally
    override ``_format_turn`` for provider-specific history format.
    """

    MAX_HISTORY_TURNS = 50
    MAX_SESSIONS = 1000

    _log_prefix: str = "Runner"

    def __init__(self, ttl_hours: int = 4) -> None:
        self._sessions: dict[str, RunnerSession] = {}
        self._ttl = timedelta(hours=ttl_hours)
        self._cleanup_task: asyncio.Task | None = None

    # -- history format hook -------------------------------------------

    def _format_turn(self, role: str, content: str) -> dict:
        """Return a single history entry.  Override for custom formats."""
        return {"role": role, "content": content}

    # -- lifecycle -----------------------------------------------------

    async def start_cleanup_loop(self, interval_minutes: int = 5) -> None:
        """Start periodic cleanup of expired sessions."""

        async def _loop():
            while True:
                await asyncio.sleep(interval_minutes * 60)
                count = self.cleanup_expired()
                if count > 0:
                    logger.info(
                        "%s session cleanup: removed %d expired sessions",
                        self._log_prefix,
                        count,
                    )

        self._cleanup_task = asyncio.create_task(_loop())

    async def stop_cleanup_loop(self) -> None:
        """Stop the periodic cleanup task."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

    # -- session CRUD --------------------------------------------------

    def get_or_create(self, session_id: str | None, agent_id: str) -> RunnerSession:
        """Get existing session or create a new one.

        Returns existing session if session_id is found.
        Creates a new session if session_id is None or not found.
        Raises ValueError if MAX_SESSIONS reached and no expired sessions
        can be reclaimed.
        """
        if session_id and session_id in self._sessions:
            session = self._sessions[session_id]
            session.last_activity = datetime.now()
            return session

        # Check capacity before creating
        if len(self._sessions) >= self.MAX_SESSIONS:
            reclaimed = self.cleanup_expired()
            if reclaimed == 0 and len(self._sessions) >= self.MAX_SESSIONS:
                raise ValueError(
                    f"Maximum sessions ({self.MAX_SESSIONS}) reached. "
                    "Cannot create new session."
                )

        new_id = str(uuid.uuid4())
        now = datetime.now()
        session = RunnerSession(
            session_id=new_id,
            agent_id=agent_id,
            created_at=now,
            last_activity=now,
        )
        self._sessions[new_id] = session
        return session

    def append_turn(self, session_id: str, role: str, content: str) -> None:
        """Append a message turn to session history.

        Applies sliding window if history exceeds MAX_HISTORY_TURNS.
        """
        if session_id not in self._sessions:
            return

        session = self._sessions[session_id]
        session.history.append(self._format_turn(role, content))
        session.last_activity = datetime.now()

        # Sliding window: keep the most recent turns
        if len(session.history) > self.MAX_HISTORY_TURNS:
            excess = len(session.history) - self.MAX_HISTORY_TURNS
            session.history = session.history[excess:]

    def update_usage(
        self,
        session_id: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> None:
        """Update session token and cost counters."""
        if session_id not in self._sessions:
            return
        session = self._sessions[session_id]
        session.total_tokens += input_tokens + output_tokens
        session.total_cost_usd += cost_usd

    def get_history(self, session_id: str) -> list[dict]:
        """Get conversation history for a session."""
        if session_id not in self._sessions:
            return []
        return list(self._sessions[session_id].history)

    def cleanup_expired(self) -> int:
        """Remove sessions that have exceeded their TTL.

        Returns the number of sessions removed.
        """
        now = datetime.now()
        expired = [
            sid
            for sid, session in self._sessions.items()
            if (now - session.last_activity) > self._ttl
        ]
        for sid in expired:
            del self._sessions[sid]
        return len(expired)

    @property
    def session_count(self) -> int:
        """Current number of active sessions."""
        return len(self._sessions)
