"""Chat History Cache.

In-memory cache for recent chat messages to reduce database queries.
"""

import time
from dataclasses import dataclass, field


@dataclass
class CacheEntry:
    """Single cache entry with data and timestamp."""

    data: list[dict]
    timestamp: float = field(default_factory=time.time)


class ChatHistoryCache:
    """In-memory cache for chat history.

    Caches recent messages per user to avoid repeated DB queries.
    TTL-based expiration with periodic cleanup.
    """

    def __init__(self, max_messages: int = 15, ttl_seconds: int = 300):
        """Initialize cache.

        Args:
            max_messages: Max messages to cache per user
            ttl_seconds: Time-to-live for cache entries (default 5 min)
        """
        self._cache: dict[str, CacheEntry] = {}
        self._ttl_seconds = ttl_seconds
        self._max_messages = max_messages
        self._hits = 0
        self._misses = 0

    def _make_key(self, user_id: int, platform: str) -> str:
        """Create cache key from user_id and platform."""
        return f"{platform}:{user_id}"

    def get(self, user_id: int, platform: str) -> list[dict] | None:
        """Get cached history for user.

        Args:
            user_id: User ID
            platform: Platform name

        Returns:
            Cached messages or None if not found/expired
        """
        key = self._make_key(user_id, platform)
        entry = self._cache.get(key)

        if entry is None:
            self._misses += 1
            return None

        # Check if expired
        if time.time() - entry.timestamp >= self._ttl_seconds:
            del self._cache[key]
            self._misses += 1
            return None

        self._hits += 1
        return entry.data.copy()  # Return copy to prevent mutation

    def set(self, user_id: int, platform: str, messages: list[dict]) -> None:
        """Cache history for user.

        Args:
            user_id: User ID
            platform: Platform name
            messages: Messages to cache (will be truncated to max_messages)
        """
        key = self._make_key(user_id, platform)
        # Store only the most recent messages
        truncated = messages[-self._max_messages :] if messages else []
        self._cache[key] = CacheEntry(data=truncated)

    def invalidate(self, user_id: int, platform: str) -> None:
        """Invalidate cache for user.

        Call this when a new message is stored.

        Args:
            user_id: User ID
            platform: Platform name
        """
        key = self._make_key(user_id, platform)
        self._cache.pop(key, None)

    def cleanup_expired(self) -> int:
        """Remove all expired entries.

        Should be called periodically to free memory.

        Returns:
            Number of entries removed
        """
        now = time.time()
        expired_keys = [
            key
            for key, entry in self._cache.items()
            if now - entry.timestamp >= self._ttl_seconds
        ]
        for key in expired_keys:
            del self._cache[key]
        return len(expired_keys)

    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()

    @property
    def size(self) -> int:
        """Current number of cached entries."""
        return len(self._cache)

    @property
    def hit_rate(self) -> float:
        """Cache hit rate (0.0 to 1.0)."""
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    def stats(self) -> dict:
        """Get cache statistics."""
        return {
            "size": self.size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": f"{self.hit_rate:.1%}",
            "ttl_seconds": self._ttl_seconds,
            "max_messages": self._max_messages,
        }
