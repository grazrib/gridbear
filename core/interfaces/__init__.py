"""GridBear Plugin Interfaces.

This module exports all base interfaces for plugin development.
"""

from core.interfaces.channel import BaseChannel, Message, MessageHandler, UserInfo
from core.interfaces.mcp_provider import BaseMCPProvider
from core.interfaces.runner import BaseRunner, RunnerResponse
from core.interfaces.service import (
    BaseAttachmentService,
    BaseImageService,
    BaseMemoryService,
    BaseService,
    BaseSessionService,
    BaseTranscriptionService,
    BaseTTSService,
)
from core.interfaces.theme import BaseTheme

__all__ = [
    # Runner
    "BaseRunner",
    "RunnerResponse",
    # Channel
    "BaseChannel",
    "Message",
    "UserInfo",
    "MessageHandler",
    # Services
    "BaseService",
    "BaseTranscriptionService",
    "BaseImageService",
    "BaseTTSService",
    "BaseMemoryService",
    "BaseSessionService",
    "BaseAttachmentService",
    # MCP
    "BaseMCPProvider",
    # Theme
    "BaseTheme",
]
