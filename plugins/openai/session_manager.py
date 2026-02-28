"""Session Manager for OpenAI multi-turn conversations.

Thin wrapper around the shared BaseSessionManager.
Messages stored in OpenAI format: {"role": "user|assistant", "content": "..."}.
"""

from core.runners.session_manager import BaseSessionManager
from core.runners.session_manager import RunnerSession as OpenAISession  # noqa: F401


class SessionManager(BaseSessionManager):
    """OpenAI-specific session manager."""

    _log_prefix = "OpenAI"
