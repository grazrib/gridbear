"""Session Manager for Claude multi-turn conversations.

Thin wrapper around the shared BaseSessionManager.
Messages stored in Claude API format: {"role": "user|assistant", "content": "..."}.
"""

from core.runners.session_manager import BaseSessionManager
from core.runners.session_manager import RunnerSession as ClaudeSession  # noqa: F401


class SessionManager(BaseSessionManager):
    """Claude-specific session manager."""

    _log_prefix = "Claude"
