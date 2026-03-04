"""Session Manager for Mistral multi-turn conversations.

Thin wrapper around the shared BaseSessionManager.
Messages stored in OpenAI-compatible format: {"role": "user|assistant", "content": "..."}.
"""

from core.runners.session_manager import BaseSessionManager
from core.runners.session_manager import RunnerSession as MistralSession  # noqa: F401


class SessionManager(BaseSessionManager):
    """Mistral-specific session manager."""

    _log_prefix = "Mistral"
