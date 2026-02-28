import os
from pathlib import Path

import aiohttp

from config.logging_config import logger
from config.settings import ATTACHMENTS_DIR


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal attacks."""
    # Get only the base filename, removing any directory components
    safe_name = os.path.basename(filename)
    # Remove any remaining dangerous characters
    safe_name = safe_name.replace("\x00", "")
    # Ensure we have a valid filename
    if not safe_name or safe_name in (".", ".."):
        safe_name = "unnamed_file"
    return safe_name


class AttachmentHandler:
    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or ATTACHMENTS_DIR

    def get_session_dir(self, session_id: int) -> Path:
        """Get or create session attachment directory."""
        session_dir = self.base_dir / str(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir

    async def download_telegram(self, file, session_id: int, filename: str) -> Path:
        """Download file from Telegram."""
        session_dir = self.get_session_dir(session_id)
        safe_filename = sanitize_filename(filename)
        file_path = session_dir / safe_filename

        await file.download_to_drive(file_path)
        logger.info(f"Downloaded Telegram file to {file_path}")
        return file_path

    async def download_discord(self, attachment, session_id: int) -> Path:
        """Download file from Discord."""
        session_dir = self.get_session_dir(session_id)
        safe_filename = sanitize_filename(attachment.filename)
        file_path = session_dir / safe_filename

        async with aiohttp.ClientSession() as http:
            async with http.get(attachment.url) as resp:
                if resp.status == 200:
                    with open(file_path, "wb") as f:
                        f.write(await resp.read())
                    logger.info(f"Downloaded Discord file to {file_path}")
                else:
                    logger.error(f"Failed to download Discord file: {resp.status}")

        return file_path

    async def cleanup_session(self, session_id: int) -> None:
        """Remove all attachments for a session."""
        session_dir = self.get_session_dir(session_id)
        if session_dir.exists():
            for f in session_dir.iterdir():
                f.unlink()
            session_dir.rmdir()
            logger.info(f"Cleaned up attachments for session {session_id}")
