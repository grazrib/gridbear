"""Session Manager for Ollama multi-turn conversations.

Thin wrapper around the shared BaseSessionManager.
Messages stored as {"role": "user|assistant", "content": "..."}.
"""

from core.runners.session_manager import BaseSessionManager
from core.runners.session_manager import RunnerSession as OllamaSession  # noqa: F401


class SessionManager(BaseSessionManager):
    """Ollama-specific session manager."""

    _log_prefix = "Ollama"
