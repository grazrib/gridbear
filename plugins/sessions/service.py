"""Session Service Plugin.

Manages user sessions with PostgreSQL storage via ORM models.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from config.logging_config import logger
from core.interfaces.service import BaseSessionService
from sessions.cache import ChatHistoryCache


@dataclass
class Session:
    """Session data object."""

    id: int
    user_id: int
    platform: str
    runner_session_id: str | None
    created_at: datetime
    updated_at: datetime


class SessionService(BaseSessionService):
    """Session management service using ORM models."""

    name = "sessions"

    def __init__(self, config: dict):
        super().__init__(config)
        self.ttl_hours = config.get("ttl_hours", 4)
        self._initialized = False
        # Chat history cache for performance
        cache_ttl = config.get("cache_ttl_seconds", 300)
        cache_max = config.get("cache_max_messages", 15)
        self._chat_cache = ChatHistoryCache(
            max_messages=cache_max, ttl_seconds=cache_ttl
        )

    async def initialize(self) -> None:
        """Initialize service. ORM handles schema/table migration at boot."""
        if self._initialized:
            return

        self._initialized = True
        logger.info("Session service initialized (ORM)")

        # Auto-migrate any unmigrated legacy messages (only once)
        if not hasattr(self, "_migration_done"):
            self._migration_done = True
            migrated = await self._migrate_messages_internal()
            if migrated > 0:
                logger.info(f"Auto-migrated {migrated} messages to chat history")

    async def shutdown(self) -> None:
        """Cleanup resources."""
        pass

    # ========== SESSION METHODS ==========

    @staticmethod
    def _to_session(row: dict) -> Session:
        """Convert a dict row to a Session dataclass."""
        return Session(
            id=row["id"],
            user_id=row["user_id"],
            platform=row["platform"],
            runner_session_id=row.get("runner_session_id"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def get_session(self, user_id: int, platform: str) -> Session | None:
        """Get active session for user, considering TTL."""
        await self.initialize()
        from plugins.sessions.models import SessionRecord

        cutoff = datetime.utcnow() - timedelta(hours=self.ttl_hours)
        results = await SessionRecord.search(
            [
                ("user_id", "=", user_id),
                ("platform", "=", platform),
                ("updated_at", ">", cutoff),
            ],
            order="updated_at DESC",
            limit=1,
        )
        return self._to_session(results[0]) if results else None

    async def create_session(self, user_id: int, platform: str) -> Session:
        """Create new session."""
        await self.initialize()
        from plugins.sessions.models import SessionRecord

        row = await SessionRecord.create(user_id=user_id, platform=platform)
        return self._to_session(row)

    async def update_runner_session_id(
        self, session_id: int, runner_session_id: str
    ) -> None:
        """Update runner session ID after first response."""
        await self.initialize()
        from plugins.sessions.models import SessionRecord

        # auto_now on updated_at handles the timestamp
        await SessionRecord.write(session_id, runner_session_id=runner_session_id)

    async def touch_session(self, session_id: int) -> None:
        """Update session timestamp (auto_now handles updated_at)."""
        await self.initialize()
        from plugins.sessions.models import SessionRecord

        await SessionRecord.write(session_id)

    async def clear_session(self, user_id: int, platform: str) -> list[int]:
        """Clear user session (for /reset command). Returns deleted session IDs."""
        await self.initialize()
        from plugins.sessions.models import SessionRecord

        domain = [("user_id", "=", user_id), ("platform", "=", platform)]
        rows = await SessionRecord.search(domain)
        session_ids = [r["id"] for r in rows]

        await SessionRecord.delete_multi(domain)
        return session_ids

    # ========== LEGACY MESSAGE METHODS ==========

    async def add_message(self, session_id: int, role: str, content: str) -> None:
        """Store message in session history."""
        await self.initialize()
        from plugins.sessions.models import SessionMessage

        await SessionMessage.create(session_id=session_id, role=role, content=content)

    async def get_history(
        self, session_id: int, limit: int | None = None
    ) -> list[dict]:
        """Get session message history."""
        await self.initialize()
        from plugins.sessions.models import SessionMessage

        rows = await SessionMessage.search(
            [("session_id", "=", session_id)],
            order="created_at",
            limit=limit or 0,
        )
        return [
            {
                "role": r["role"],
                "content": r["content"],
                "created_at": r["created_at"].isoformat()
                if isinstance(r["created_at"], datetime)
                else r["created_at"],
            }
            for r in rows
        ]

    # ========== CLEANUP ==========

    async def cleanup_expired(self) -> int:
        """Remove expired sessions and cache entries. Returns count of deleted sessions."""
        await self.initialize()
        from plugins.sessions.models import SessionRecord

        # Cleanup cache
        cache_cleaned = self._chat_cache.cleanup_expired()
        if cache_cleaned > 0:
            logger.debug(f"Cleaned {cache_cleaned} expired cache entries")

        cutoff = datetime.utcnow() - timedelta(hours=self.ttl_hours)
        domain = [("updated_at", "<", cutoff)]

        count = await SessionRecord.count(domain)
        # CASCADE handles messages deletion
        await SessionRecord.delete_multi(domain)
        return count

    def get_cache_stats(self) -> dict:
        """Get chat history cache statistics."""
        return self._chat_cache.stats()

    # ========== CHAT HISTORY METHODS ==========

    async def store_chat_message(
        self,
        user_id: int,
        platform: str,
        role: str,
        content: str,
        username: str | None = None,
    ) -> int:
        """Store a message in persistent chat history.

        Returns:
            Message ID
        """
        await self.initialize()
        from plugins.sessions.models import ChatHistory

        # Invalidate cache - new message means cache is stale
        self._chat_cache.invalidate(user_id, platform)

        row = await ChatHistory.create(
            user_id=user_id,
            platform=platform,
            username=username,
            role=role,
            content=content,
        )
        return row["id"]

    async def search_chat_history(
        self,
        user_id: int,
        platform: str,
        query: str,
        limit: int = 20,
    ) -> list[dict]:
        """Search chat history using app-level substring match on decrypted content."""
        await self.initialize()
        from plugins.sessions.models import ChatHistory

        # Fetch recent messages and search in Python (content is encrypted)
        fetch_limit = 500
        rows = await ChatHistory.search(
            [("user_id", "=", user_id), ("platform", "=", platform)],
            order="created_at DESC",
            limit=fetch_limit,
        )

        query_lower = query.lower()
        results = []
        for row in rows:
            content = row.get("content", "")
            if query_lower in content.lower():
                results.append(
                    {
                        "id": row["id"],
                        "role": row["role"],
                        "content": content,
                        "highlighted": content,
                        "username": row["username"],
                        "created_at": row["created_at"].isoformat()
                        if isinstance(row["created_at"], datetime)
                        else row["created_at"],
                    }
                )
                if len(results) >= limit:
                    break

        return results

    async def get_recent_chat_history(
        self,
        user_id: int,
        platform: str,
        limit: int = 50,
        before_id: int | None = None,
    ) -> list[dict]:
        """Get recent chat history for a user.

        Returns:
            List of recent messages (newest first)
        """
        await self.initialize()
        from plugins.sessions.models import ChatHistory

        # Try cache first (only for standard queries without pagination)
        if before_id is None and limit <= self._chat_cache._max_messages:
            cached = self._chat_cache.get(user_id, platform)
            if cached is not None:
                return cached[:limit]

        domain = [("user_id", "=", user_id), ("platform", "=", platform)]
        if before_id:
            domain.append(("id", "<", before_id))

        rows = await ChatHistory.search(domain, order="created_at DESC", limit=limit)
        messages = [
            {
                "id": r["id"],
                "role": r["role"],
                "content": r["content"],
                "username": r["username"],
                "created_at": r["created_at"].isoformat()
                if isinstance(r["created_at"], datetime)
                else r["created_at"],
            }
            for r in rows
        ]

        # Cache results for non-paginated queries
        if before_id is None and messages:
            self._chat_cache.set(user_id, platform, messages)

        return messages

    async def get_chat_history_stats(self, user_id: int, platform: str) -> dict:
        """Get statistics about chat history."""
        await self.initialize()
        from plugins.sessions.models import ChatHistory

        rows = await ChatHistory.raw_search(
            """
            SELECT COUNT(*) as total,
                   MIN(created_at) as first_date,
                   MAX(created_at) as last_date
            FROM {table}
            WHERE user_id = %s AND platform = %s
            """,
            (user_id, platform),
        )
        row = rows[0] if rows else None
        return {
            "total_messages": row["total"] if row else 0,
            "first_message_date": row["first_date"].isoformat()
            if row and row["first_date"]
            else None,
            "last_message_date": row["last_date"].isoformat()
            if row and row["last_date"]
            else None,
        }

    async def cleanup_old_chat_history(self, days: int = 90) -> int:
        """Remove chat history older than specified days."""
        await self.initialize()
        from plugins.sessions.models import ChatHistory

        cutoff = datetime.utcnow() - timedelta(days=days)
        return await ChatHistory.delete_multi([("created_at", "<", cutoff)])

    # ========== MIGRATION METHODS ==========

    async def _migrate_messages_internal(self) -> int:
        """Migrate legacy session messages to persistent chat history."""
        from plugins.sessions.models import ChatHistory

        return await ChatHistory.raw_execute(
            """
            INSERT INTO {table} (user_id, platform, username, role, content, created_at)
            SELECT DISTINCT s.user_id, s.platform, NULL, m.role, m.content, m.created_at
            FROM "chat"."messages" m
            JOIN "chat"."sessions" s ON m.session_id = s.id
            WHERE NOT EXISTS (
                SELECT 1 FROM {table} ch
                WHERE ch.user_id = s.user_id
                  AND ch.platform = s.platform
                  AND ch.role = m.role
                  AND ch.created_at = m.created_at
            )
            """,
        )

    async def migrate_messages_to_history(self) -> int:
        """Migrate old messages from sessions to chat_history."""
        await self.initialize()
        return await self._migrate_messages_internal()

    async def import_chat_history(
        self,
        messages: list[dict],
        user_id: int,
        platform: str,
        username: str | None = None,
    ) -> int:
        """Import chat history from external source."""
        await self.initialize()
        from plugins.sessions.models import ChatHistory

        imported = 0

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            created_at = msg.get("created_at")

            if not content:
                continue

            # Parse created_at if string
            if isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(created_at)
                except ValueError:
                    created_at = datetime.utcnow()
            elif created_at is None:
                created_at = datetime.utcnow()

            # Check for duplicates (cannot compare encrypted content in SQL,
            # so use metadata columns only — user+platform+role+timestamp)
            exists = await ChatHistory.exists(
                [
                    ("user_id", "=", user_id),
                    ("platform", "=", platform),
                    ("role", "=", role),
                    ("created_at", "=", created_at),
                ]
            )
            if exists:
                continue

            await ChatHistory.create(
                user_id=user_id,
                platform=platform,
                username=username,
                role=role,
                content=content,
                created_at=created_at,
            )
            imported += 1

        logger.info(f"Imported {imported} messages for user {user_id} on {platform}")
        return imported
