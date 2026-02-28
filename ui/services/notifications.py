"""Notification service — lifecycle management, SSE broadcast, deduplication."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from config.logging_config import logger
from core.registry import get_database

_ADMIN_KEY = "__admin__"
_MAX_LISTENERS_PER_KEY = 2


class NotificationService:
    """Singleton service for notification CRUD, deduplication, and SSE broadcast."""

    _instance: NotificationService | None = None

    def __init__(self) -> None:
        self._listeners: dict[str, list[asyncio.Queue]] = {}

    @classmethod
    def get(cls) -> NotificationService:
        """Return the singleton instance, creating it on first call."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create(
        self,
        category: str,
        severity: str,
        title: str,
        message: str | None = None,
        source: str | None = None,
        user_id: str | None = None,
        action_url: str | None = None,
        expires_at: datetime | None = None,
        dedupe_window_minutes: int = 60,
    ) -> dict[str, Any] | None:
        """Create a notification with deduplication.

        Returns the created row as dict, or None if a duplicate exists
        within *dedupe_window_minutes*.
        """
        db = get_database()

        # --- deduplication ---
        if dedupe_window_minutes > 0:
            dup_sql = (
                "SELECT id FROM notifications "
                "WHERE category = %s AND source IS NOT DISTINCT FROM %s "
                "AND user_id IS NOT DISTINCT FROM %s "
                "AND created_at > NOW() - INTERVAL '%s minutes'"
            )
            dup = await db.fetch_one(
                dup_sql, (category, source, user_id, dedupe_window_minutes)
            )
            if dup:
                logger.debug(
                    "Notification deduplicated: %s/%s for user %s",
                    category,
                    source,
                    user_id,
                )
                return None

        # --- insert ---
        row = await db.fetch_one(
            "INSERT INTO notifications "
            "(category, severity, title, message, source, "
            "user_id, action_url, expires_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "RETURNING *",
            (
                category,
                severity,
                title,
                message,
                source,
                user_id,
                action_url,
                expires_at,
            ),
        )

        if row:
            notif = dict(row)
            await self._broadcast(notif)
            return notif
        return None

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    async def get_unread_count(
        self,
        user_id: str | None = None,
        is_admin: bool = False,
    ) -> int:
        """Return the number of unread notifications visible to the caller."""
        db = get_database()
        if is_admin:
            row = await db.fetch_one(
                "SELECT COUNT(*) AS cnt FROM notifications WHERE is_read = FALSE"
            )
        else:
            row = await db.fetch_one(
                "SELECT COUNT(*) AS cnt FROM notifications "
                "WHERE is_read = FALSE AND (user_id = %s OR user_id IS NULL)",
                (user_id,),
            )
        return row["cnt"] if row else 0

    async def get_list(
        self,
        user_id: str | None = None,
        is_admin: bool = False,
        unread_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Paginated notification list ordered by created_at DESC."""
        db = get_database()
        conditions: list[str] = []
        params: list[Any] = []

        if not is_admin:
            conditions.append("(user_id = %s OR user_id IS NULL)")
            params.append(user_id)

        if unread_only:
            conditions.append("is_read = FALSE")

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        sql = (
            f"SELECT * FROM notifications {where} "
            f"ORDER BY created_at DESC LIMIT %s OFFSET %s"
        )
        params.extend([limit, offset])

        rows = await db.fetch_all(sql, tuple(params))
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Mark read
    # ------------------------------------------------------------------

    async def mark_read(
        self,
        notification_id: int,
        user_id: str | None = None,
        is_admin: bool = False,
    ) -> bool:
        """Mark a single notification as read. Returns True if updated."""
        db = get_database()
        if is_admin:
            row = await db.fetch_one(
                "UPDATE notifications SET is_read = TRUE "
                "WHERE id = %s AND is_read = FALSE RETURNING id",
                (notification_id,),
            )
        else:
            row = await db.fetch_one(
                "UPDATE notifications SET is_read = TRUE "
                "WHERE id = %s AND is_read = FALSE "
                "AND (user_id = %s OR user_id IS NULL) RETURNING id",
                (notification_id, user_id),
            )
        return row is not None

    async def resolve_by_source(
        self,
        category: str,
        sources: list[str],
    ) -> int:
        """Mark unread notifications as read for resolved sources.

        Used by plugin health monitoring to auto-dismiss notifications
        when a plugin returns to healthy status.
        """
        if not sources:
            return 0
        db = get_database()
        placeholders = ", ".join(["%s"] * len(sources))
        row = await db.fetch_one(
            f"WITH resolved AS ("
            f"  UPDATE notifications SET is_read = TRUE"
            f"  WHERE category = %s AND source IN ({placeholders})"
            f"  AND is_read = FALSE RETURNING id"
            f") SELECT COUNT(*) AS cnt FROM resolved",
            (category, *sources),
        )
        return row["cnt"] if row else 0

    async def mark_all_read(
        self,
        user_id: str | None = None,
        is_admin: bool = False,
    ) -> int:
        """Mark all visible notifications as read. Returns count updated."""
        db = get_database()
        if is_admin:
            row = await db.fetch_one(
                "WITH updated AS ("
                "  UPDATE notifications SET is_read = TRUE "
                "  WHERE is_read = FALSE RETURNING id"
                ") SELECT COUNT(*) AS cnt FROM updated"
            )
        else:
            row = await db.fetch_one(
                "WITH updated AS ("
                "  UPDATE notifications SET is_read = TRUE "
                "  WHERE is_read = FALSE "
                "  AND (user_id = %s OR user_id IS NULL) RETURNING id"
                ") SELECT COUNT(*) AS cnt FROM updated",
                (user_id,),
            )
        return row["cnt"] if row else 0

    # ------------------------------------------------------------------
    # SSE subscribe / unsubscribe
    # ------------------------------------------------------------------

    def subscribe(
        self,
        user_id: str | None = None,
        is_admin: bool = False,
    ) -> asyncio.Queue:
        """Register an SSE listener and return its queue.

        Limits to _MAX_LISTENERS_PER_KEY connections per key — oldest
        queues are evicted by sending a sentinel to trigger cleanup.
        """
        key = _ADMIN_KEY if is_admin else (user_id or _ADMIN_KEY)
        queue: asyncio.Queue = asyncio.Queue()
        listeners = self._listeners.setdefault(key, [])

        # Evict oldest connections beyond limit
        while len(listeners) >= _MAX_LISTENERS_PER_KEY:
            old = listeners.pop(0)
            try:
                old.put_nowait(None)  # sentinel → triggers disconnect
            except asyncio.QueueFull:
                pass
            logger.debug("SSE evicted stale listener for key=%s", key)

        listeners.append(queue)
        logger.debug("SSE subscribe: key=%s (total=%d)", key, len(listeners))
        return queue

    def unsubscribe(
        self,
        user_id: str | None = None,
        queue: asyncio.Queue | None = None,
        is_admin: bool = False,
    ) -> None:
        """Remove a previously registered SSE listener."""
        key = _ADMIN_KEY if is_admin else (user_id or _ADMIN_KEY)
        listeners = self._listeners.get(key, [])
        if queue in listeners:
            listeners.remove(queue)
            logger.debug("SSE unsubscribe: key=%s (remaining=%d)", key, len(listeners))
        if not listeners:
            self._listeners.pop(key, None)

    # ------------------------------------------------------------------
    # Broadcast
    # ------------------------------------------------------------------

    async def _broadcast(self, notif: dict[str, Any]) -> None:
        """Push a notification to all relevant SSE listeners.

        - Admin listeners always receive every notification.
        - If the notification has a user_id, send to that user's listeners.
        - If user_id is None (broadcast), send to all non-admin listeners too.
        """
        payload = self._serialize(notif)

        # Always notify admins
        for queue in list(self._listeners.get(_ADMIN_KEY, [])):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning("Admin SSE queue full, dropping notification")

        target_user = notif.get("user_id")
        if target_user:
            # Targeted notification — send to that user only
            for queue in list(self._listeners.get(target_user, [])):
                try:
                    queue.put_nowait(payload)
                except asyncio.QueueFull:
                    logger.warning("User SSE queue full for %s, dropping", target_user)
        else:
            # Broadcast — send to every non-admin listener
            for key, queues in list(self._listeners.items()):
                if key == _ADMIN_KEY:
                    continue
                for queue in list(queues):
                    try:
                        queue.put_nowait(payload)
                    except asyncio.QueueFull:
                        logger.warning("User SSE queue full for %s, dropping", key)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def cleanup_expired(self) -> int:
        """Delete expired notifications. Returns count deleted."""
        db = get_database()
        row = await db.fetch_one(
            "WITH deleted AS ("
            "  DELETE FROM notifications "
            "  WHERE expires_at IS NOT NULL AND expires_at < NOW() "
            "  RETURNING id"
            ") SELECT COUNT(*) AS cnt FROM deleted"
        )
        count = row["cnt"] if row else 0
        if count:
            logger.info("Cleaned up %d expired notifications", count)
        return count

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize(notif: dict[str, Any]) -> str:
        """Convert a notification dict to a JSON string for SSE delivery.

        Datetime fields are serialised to ISO-8601 strings.
        """

        def _default(obj: Any) -> str:
            if isinstance(obj, datetime):
                return obj.isoformat()
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

        return json.dumps(notif, default=_default)
