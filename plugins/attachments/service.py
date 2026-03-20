"""Attachment Service Plugin.

Handles attachment storage and cleanup.
"""

import shutil
import time
from pathlib import Path

import aiohttp

from config.logging_config import logger
from core.interfaces.service import BaseAttachmentService


class AttachmentService(BaseAttachmentService):
    """Attachment handling service."""

    name = "attachments"

    def __init__(self, config: dict):
        super().__init__(config)
        self.base_dir = Path(config.get("base_dir", "data/attachments"))

    async def initialize(self) -> None:
        """Initialize attachment directory."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Attachment service initialized at {self.base_dir}")

    async def shutdown(self) -> None:
        """Cleanup resources."""
        pass

    def get_session_dir(self, session_id: int) -> Path:
        """Get or create session attachment directory."""
        session_dir = self.base_dir / str(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir

    async def save_attachment(
        self,
        file_path: str,
        session_id: int,
        filename: str | None = None,
    ) -> str:
        """Save attachment for a session by copying from source path."""
        session_dir = self.get_session_dir(session_id)
        source = Path(file_path)

        if filename is None:
            filename = source.name

        dest_path = session_dir / filename

        if source.exists():
            import shutil

            shutil.copy2(source, dest_path)
            logger.info(f"Saved attachment to {dest_path}")

        return str(dest_path)

    async def download_telegram(self, file, session_id: int, filename: str) -> Path:
        """Download file from Telegram."""
        session_dir = self.get_session_dir(session_id)
        file_path = session_dir / filename

        await file.download_to_drive(file_path)
        logger.info(f"Downloaded Telegram file to {file_path}")
        return file_path

    async def download_discord(self, attachment, session_id: int) -> Path:
        """Download file from Discord."""
        session_dir = self.get_session_dir(session_id)
        file_path = session_dir / attachment.filename

        async with aiohttp.ClientSession() as http:
            async with http.get(attachment.url) as resp:
                if resp.status == 200:
                    with open(file_path, "wb") as f:
                        f.write(await resp.read())
                    logger.info(f"Downloaded Discord file to {file_path}")
                else:
                    logger.error(f"Failed to download Discord file: {resp.status}")

        return file_path

    async def get_attachments(self, session_id: int) -> list[str]:
        """Get all attachments for a session."""
        session_dir = self.get_session_dir(session_id)
        if not session_dir.exists():
            return []

        return [str(f) for f in session_dir.iterdir() if f.is_file()]

    async def cleanup_session(self, session_id: int) -> None:
        """Remove all attachments for a session."""
        session_dir = self.base_dir / str(session_id)
        if session_dir.exists():
            shutil.rmtree(session_dir)
            logger.info(f"Cleaned up attachments for session {session_id}")

    async def cleanup_expired(self, max_age_hours: int = 24) -> int:
        """Remove old attachments.

        Args:
            max_age_hours: Maximum age in hours

        Returns:
            Number of files cleaned up
        """
        if not self.base_dir.exists():
            return 0

        cutoff_time = time.time() - (max_age_hours * 3600)
        cleaned = 0

        for session_dir in self.base_dir.iterdir():
            if not session_dir.is_dir():
                continue

            try:
                dir_mtime = session_dir.stat().st_mtime
                if dir_mtime < cutoff_time:
                    cleaned += sum(1 for f in session_dir.rglob("*") if f.is_file())
                    shutil.rmtree(session_dir)
                    logger.debug(f"Cleaned up expired session dir: {session_dir.name}")
            except Exception as e:
                logger.warning(f"Error cleaning up {session_dir}: {e}")

        if cleaned > 0:
            logger.info(f"Cleaned up {cleaned} expired attachment files")

        return cleaned
