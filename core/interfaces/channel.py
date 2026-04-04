"""Base Channel Interface.

Defines the abstract interface for messaging channels (Telegram, Discord, etc).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Awaitable, Callable

if TYPE_CHECKING:
    from core.agent import Agent
    from core.interfaces.service import BaseSchedulerService
    from core.plugin_manager import PluginManager


@dataclass
class Message:
    """Incoming message from a channel."""

    user_id: int
    username: str | None
    text: str
    attachments: list[str] = field(default_factory=list)
    platform: str = ""
    respond_with_voice: bool = (
        False  # If True, response will be TTS - no emojis/special chars
    )
    is_group_chat: bool = False
    context_prompt: str | None = None
    channel_metadata: dict = field(default_factory=dict)


@dataclass
class UserInfo:
    """User information from a channel."""

    user_id: int
    username: str | None
    display_name: str | None
    platform: str
    unified_id: str | None = None


MessageHandler = Callable[[Message, UserInfo], Awaitable[str]]


class BaseChannel(ABC):
    """Abstract interface for messaging channels."""

    platform: str = ""

    def __init__(self, config: dict, agent_name: str | None = None):
        """Initialize channel with configuration.

        Args:
            config: Plugin configuration dict
            agent_name: Optional agent name for multi-agent mode
        """
        self.config = config
        self.agent_name = agent_name
        self._message_handler: MessageHandler | None = None
        self._plugin_manager: "PluginManager | None" = None
        self._task_scheduler: "BaseSchedulerService | None" = None
        self._agent: "Agent | None" = None
        self._agent_context: dict = {}  # Agent-specific context

    def set_message_handler(self, handler: MessageHandler) -> None:
        """Register handler for incoming messages.

        Args:
            handler: Async function that processes messages and returns response text
        """
        self._message_handler = handler

    def set_plugin_manager(self, manager: "PluginManager") -> None:
        """Set reference to plugin manager for accessing services.

        Args:
            manager: The plugin manager instance
        """
        self._plugin_manager = manager

    def set_agent(self, agent: "Agent") -> None:
        """Set reference to the owning agent for per-agent service lookup.

        Args:
            agent: The Agent instance that owns this channel
        """
        self._agent = agent

    def set_task_scheduler(self, scheduler: "BaseSchedulerService") -> None:
        """Set reference to scheduler service for memo/scheduled tasks.

        Args:
            scheduler: A service implementing BaseSchedulerService
        """
        self._task_scheduler = scheduler

    def set_agent_context(self, context: dict) -> None:
        """Set agent-specific context for multi-agent mode.

        Args:
            context: Dictionary containing agent configuration:
                - name: Agent internal name
                - display_name: Agent display name
                - system_prompt: Agent personality
                - voice: Voice configuration dict
                - mcp_permissions: Allowed MCP servers
                - locale: Default language
        """
        self._agent_context = context

    def get_agent_context(self) -> dict:
        """Get agent context.

        Returns:
            Agent context dictionary or empty dict if not in multi-agent mode
        """
        return self._agent_context

    @abstractmethod
    async def start(self) -> None:
        """Start the channel (begin receiving messages)."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop the channel gracefully."""
        pass

    @abstractmethod
    async def send_message(
        self,
        user_id: int,
        text: str,
        attachments: list[str] | None = None,
    ) -> None:
        """Send message to a user.

        Args:
            user_id: Target user identifier
            text: Message text to send
            attachments: Optional list of file paths to attach
        """
        pass

    @abstractmethod
    async def send_file(
        self,
        user_id: int | str,
        file_path: str,
        caption: str | None = None,
    ) -> bool:
        """Send a file to a user.

        Args:
            user_id: Target user/chat identifier (int for Telegram, str for others).
                     Each adapter is responsible for converting to the appropriate type.
            file_path: Absolute path to the file
            caption: Optional caption/message to accompany the file

        Returns:
            True if file was sent successfully
        """
        pass

    @abstractmethod
    async def get_user_info(self, user_id: int) -> UserInfo | None:
        """Get user information.

        Args:
            user_id: User identifier

        Returns:
            UserInfo or None if user not found
        """
        pass

    def is_authorized(self, user_id: int, username: str | None) -> bool:
        """Check if user is authorized to use this channel.

        In multi-agent mode, checks against agent-specific authorized_users.
        In legacy mode, delegates to ConfigManager.

        Args:
            user_id: User identifier
            username: Optional username

        Returns:
            True if user is authorized
        """
        from config.logging_config import logger

        authorized_users = self.config.get("authorized_users", [])
        logger.debug(
            f"Authorization check: user_id={user_id}, username={username}, authorized_users={authorized_users}"
        )

        if not authorized_users:
            logger.debug("No allowed_users configured - access denied")
            return False

        # Check user ID as string
        if str(user_id) in authorized_users:
            logger.debug(f"User {user_id} authorized by ID")
            return True
        # Check @username
        if username:
            username_with_at = f"@{username.lower()}"
            username_lower = username.lower()
            for auth_user in authorized_users:
                auth_lower = auth_user.lower()
                if auth_lower == username_lower or auth_lower == username_with_at:
                    logger.debug(f"User {username} authorized by username match")
                    return True
        logger.debug(f"User {username} NOT authorized - no match found")
        return False

    async def initialize(self) -> None:
        """Optional initialization setup."""
        pass

    async def shutdown(self) -> None:
        """Optional cleanup on shutdown (alias for stop)."""
        await self.stop()
