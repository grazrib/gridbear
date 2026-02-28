"""Transcription provider using OpenAI Whisper API."""

from pathlib import Path

import httpx

from config.logging_config import logger
from core.interfaces.service import BaseTranscriptionService
from ui.secrets_manager import secrets_manager

WHISPER_API_URL = "https://api.openai.com/v1/audio/transcriptions"


class TranscriptionOpenAIService(BaseTranscriptionService):
    """Audio transcription using OpenAI Whisper."""

    name = "transcription-openai"

    def __init__(self, config: dict):
        super().__init__(config)
        self.model = config.get("model", "whisper-1")
        self.language = config.get("language", "it")
        self.api_key = secrets_manager.get_plain("OPENAI_API_KEY")

    async def initialize(self) -> None:
        if not self.api_key:
            logger.warning("OPENAI_API_KEY not configured for Whisper transcription")
        else:
            logger.info("Transcription-openai initialized with model %s", self.model)

    async def shutdown(self) -> None:
        pass

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def transcribe(self, audio_path: str, language: str | None = None) -> str:
        """Transcribe audio file to text via Whisper API.

        Args:
            audio_path: Path to audio file (ogg, mp3, wav, etc.)
            language: Language code (default: configured language)

        Returns:
            Transcribed text or empty string on error
        """
        if not self.api_key:
            logger.error("OPENAI_API_KEY not configured for Whisper transcription")
            return ""

        path = Path(audio_path)
        if not path.exists():
            logger.error("Audio file not found: %s", audio_path)
            return ""

        lang = language or self.language

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                with open(path, "rb") as audio_file:
                    files = {
                        "file": (path.name, audio_file, "audio/ogg"),
                    }
                    data = {
                        "model": self.model,
                        "language": lang,
                    }
                    headers = {
                        "Authorization": f"Bearer {self.api_key}",
                    }

                    response = await client.post(
                        WHISPER_API_URL,
                        files=files,
                        data=data,
                        headers=headers,
                    )

                    if response.status_code == 200:
                        result = response.json()
                        text = result.get("text", "").strip()
                        logger.info("Transcribed audio: %s...", text[:100])
                        return text
                    else:
                        logger.error(
                            "Whisper API error: %s - %s",
                            response.status_code,
                            response.text,
                        )
                        return ""

        except Exception:
            logger.exception("Whisper transcription failed")
            return ""
