"""Base Service Interfaces.

Defines abstract interfaces for shared services (transcription, image, memory, etc).
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.plugin_manager import PluginManager


class BaseService(ABC):
    """Abstract interface for shared services."""

    name: str = ""

    def __init__(self, config: dict):
        """Initialize service with configuration.

        Args:
            config: Plugin configuration dict
        """
        self.config = config
        self._plugin_manager: "PluginManager | None" = None

    def set_plugin_manager(self, manager: "PluginManager") -> None:
        """Set reference to plugin manager for accessing other services.

        Args:
            manager: The plugin manager instance
        """
        self._plugin_manager = manager

    @abstractmethod
    async def initialize(self) -> None:
        """Setup the service."""
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """Cleanup resources."""
        pass

    def get_dependencies(self) -> list[str]:
        """List of other services this service depends on.

        Returns:
            List of service names that must be loaded first
        """
        return []


class BaseTranscriptionService(BaseService):
    """Interface for audio transcription services."""

    @abstractmethod
    async def transcribe(self, audio_path: str, language: str | None = None) -> str:
        """Transcribe audio file to text.

        Args:
            audio_path: Path to audio file
            language: Optional language code hint (e.g. 'it', 'en')

        Returns:
            Transcribed text
        """
        pass


class BaseImageService(BaseService):
    """Interface for image generation services."""

    @abstractmethod
    async def generate(self, prompt: str, size: str = "1024x1024") -> str:
        """Generate image from prompt.

        Args:
            prompt: Description of image to generate
            size: Image dimensions (e.g., "1024x1024")

        Returns:
            Path to generated image file
        """
        pass


class BaseTTSService(BaseService):
    """Interface for text-to-speech services."""

    @abstractmethod
    async def synthesize(self, text: str, voice: str = "default") -> str:
        """Synthesize text to audio.

        Args:
            text: Text to convert to speech
            voice: Voice identifier

        Returns:
            Path to audio file
        """
        pass


class BaseMemoryService(BaseService):
    """Interface for conversational memory services."""

    @property
    @abstractmethod
    def enabled(self) -> bool:
        """Whether the memory backend is available."""
        ...

    @abstractmethod
    async def add_memory(
        self, content: str, user_id: str, metadata: dict | None = None
    ) -> None:
        """Store a declarative memory (backward-compat alias)."""
        ...

    @abstractmethod
    async def add_episodic_memory(
        self,
        user_message: str,
        assistant_response: str,
        user_id: str,
        platform: str,
        metadata: dict | None = None,
    ) -> None:
        """Store a conversation turn in episodic memory."""
        ...

    @abstractmethod
    async def add_declarative_memory(
        self, content: str, user_id: str, metadata: dict | None = None
    ) -> None:
        """Store extracted facts in declarative memory."""
        ...

    @abstractmethod
    async def get_relevant(
        self, query: str, user_id: str, limit: int = 5
    ) -> list[dict]:
        """Retrieve relevant memories from both episodic and declarative."""
        ...

    @abstractmethod
    async def search_episodic(
        self, query: str, user_id: str, limit: int = 5
    ) -> list[dict]:
        """Search episodic memory for relevant past conversations."""
        ...

    @abstractmethod
    async def search_declarative(
        self, query: str, user_id: str, limit: int = 5
    ) -> list[dict]:
        """Search declarative memory for relevant facts."""
        ...

    @abstractmethod
    async def delete_memory(
        self, memory_id: str, memory_type: str | None = None
    ) -> bool:
        """Delete a specific memory by ID."""
        ...

    @abstractmethod
    def get_all_memories(
        self,
        platform: str,
        username: str,
        memory_type: str | None = None,
    ) -> list[dict]:
        """Get all memories for a user."""
        ...

    @abstractmethod
    def get_memory_stats(
        self, platform: str | None = None, username: str | None = None
    ) -> dict:
        """Get memory statistics."""
        ...

    @abstractmethod
    def clear_user_memories(
        self,
        platform: str,
        username: str,
        memory_type: str | None = None,
    ) -> None:
        """Clear all memories for a user."""
        ...


class BaseSchedulerService(BaseService):
    """Interface for scheduling services (memos, reminders, timed tasks).

    Plugins that provide scheduling capabilities should inherit from this
    interface so channels can discover them without hardcoding plugin names.
    """

    @abstractmethod
    def set_callback(self, callback: Any) -> None:
        """Set callback for scheduled task execution."""
        ...

    @abstractmethod
    async def add_memo(
        self,
        user_id: int,
        platform: str,
        schedule_type: str,
        prompt: str,
        description: str,
        cron: str | None = None,
        run_at: Any | None = None,
    ) -> int:
        """Schedule a new memo/reminder."""
        ...

    @abstractmethod
    async def list_memos(self, user_id: int, platform: str) -> list[dict]:
        """List all memos for a user on a platform."""
        ...

    @abstractmethod
    async def delete_memo(self, memo_id: int, user_id: int) -> bool:
        """Delete a scheduled memo."""
        ...


class BaseSessionService(BaseService):
    """Interface for session management services."""

    @abstractmethod
    async def get_session(self, user_id: int, platform: str) -> Any:
        """Get or create session for user.

        Args:
            user_id: User identifier
            platform: Platform name (telegram, discord, etc)

        Returns:
            Session object
        """
        pass

    @abstractmethod
    async def create_session(self, user_id: int, platform: str) -> Any:
        """Create new session for user.

        Args:
            user_id: User identifier
            platform: Platform name

        Returns:
            New session object
        """
        pass

    @abstractmethod
    async def add_message(self, session_id: int, role: str, content: str) -> None:
        """Add message to session history.

        Args:
            session_id: Session identifier
            role: Message role (user, assistant, system)
            content: Message content
        """
        pass

    @abstractmethod
    async def get_history(
        self, session_id: int, limit: int | None = None
    ) -> list[dict]:
        """Get session message history.

        Args:
            session_id: Session identifier
            limit: Maximum number of messages

        Returns:
            List of message records
        """
        pass

    @abstractmethod
    async def cleanup_expired(self) -> int:
        """Remove expired sessions.

        Returns:
            Number of sessions cleaned up
        """
        pass


class BaseAttachmentService(BaseService):
    """Interface for attachment handling services."""

    @abstractmethod
    async def save_attachment(
        self,
        file_path: str,
        session_id: int,
        filename: str | None = None,
    ) -> str:
        """Save attachment for a session.

        Args:
            file_path: Source file path
            session_id: Session identifier
            filename: Optional custom filename

        Returns:
            Path where attachment was saved
        """
        pass

    @abstractmethod
    async def get_attachments(self, session_id: int) -> list[str]:
        """Get all attachments for a session.

        Args:
            session_id: Session identifier

        Returns:
            List of attachment file paths
        """
        pass

    @abstractmethod
    async def cleanup_session(self, session_id: int) -> None:
        """Remove all attachments for a session.

        Args:
            session_id: Session identifier
        """
        pass

    @abstractmethod
    async def cleanup_expired(self, max_age_hours: int = 24) -> int:
        """Remove old attachments.

        Args:
            max_age_hours: Maximum age in hours

        Returns:
            Number of files cleaned up
        """
        pass
