"""Session Manager for Gemini multi-turn conversations.

Thin wrapper around the shared BaseSessionManager.
Messages stored in Gemini format: {"role": "user|model", "parts": [{"text": "..."}]}.
"""

from core.runners.session_manager import BaseSessionManager
from core.runners.session_manager import RunnerSession as GeminiSession  # noqa: F401


class SessionManager(BaseSessionManager):
    """Gemini-specific session manager with parts-based history format."""

    _log_prefix = "Gemini"

    def _format_turn(self, role: str, content: str) -> dict:
        """Gemini uses ``parts`` instead of ``content``."""
        return {"role": role, "parts": [{"text": content}]}
