"""Google Service Account credential management.

Centralized SA storage for all Google MCP plugins (Sheets, Calendar, Drive).
Credentials stored in vault as base64-encoded SA JSON.
"""

from config.logging_config import logger
from core.interfaces.service import BaseService


class GoogleSAService(BaseService):
    """Manages Google Service Account credentials in the secrets vault."""

    name = "google-sa"

    async def initialize(self) -> None:
        logger.info("Google SA service initialized")

    async def shutdown(self) -> None:
        pass
