"""Text-to-Speech Service using OpenAI TTS."""

import uuid
from pathlib import Path

import httpx

from config.logging_config import logger
from core.interfaces.service import BaseTTSService
from ui.secrets_manager import secrets_manager


class OpenAITTSService(BaseTTSService):
    """TTS service using OpenAI Text-to-Speech API."""

    name = "tts"

    # Available voices
    VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]

    def __init__(self, config: dict):
        self.config = config
        self.model = config.get("model", "tts-1")
        self.default_voice = config.get("default_voice", "nova")
        self.voices = config.get(
            "voices",
            {
                "en": "nova",
                "it": "nova",
            },
        )
        self.output_dir = Path(config.get("output_dir", "data/tts"))
        self.api_key = secrets_manager.get_plain("OPENAI_API_KEY")

    async def initialize(self) -> None:
        """Initialize OpenAI TTS service."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if not self.api_key:
            logger.warning("OPENAI_API_KEY not set - TTS will fail")
        logger.info(
            f"OpenAI TTS service initialized with model: {self.model}, voice: {self.default_voice}"
        )

    async def shutdown(self) -> None:
        """Cleanup TTS service."""
        pass

    def get_voice_for_locale(self, locale: str) -> str:
        """Get the voice name for a given locale."""
        return self.voices.get(locale.lower(), self.default_voice)

    async def synthesize(
        self,
        text: str,
        voice: str | None = None,
        locale: str | None = None,
    ) -> str:
        """Convert text to speech and return the audio file path.

        Args:
            text: Text to convert to speech
            voice: Voice name. If None, uses locale or default.
            locale: Locale code (e.g., "it", "en"). Used to select voice if voice is None.

        Returns:
            Path to the generated audio file (MP3)
        """
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY not configured")

        if not voice:
            if locale:
                voice = self.get_voice_for_locale(locale)
            else:
                voice = self.default_voice

        # Validate voice
        if voice not in self.VOICES:
            voice = self.default_voice

        output_path = self.output_dir / f"tts_{uuid.uuid4().hex}.mp3"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.openai.com/v1/audio/speech",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "input": text,
                        "voice": voice,
                        "response_format": "mp3",
                    },
                    timeout=60.0,
                )
                response.raise_for_status()

                with open(output_path, "wb") as f:
                    f.write(response.content)

            logger.debug(f"OpenAI TTS generated: {output_path} (voice: {voice})")
            return str(output_path)

        except Exception as e:
            logger.exception(f"OpenAI TTS error: {e}")
            raise

    async def list_voices(self, locale: str | None = None) -> list[dict]:
        """List available voices."""
        # OpenAI has fixed voices that work for all languages
        return [
            {"name": "alloy", "locale": "multilingual", "gender": "neutral"},
            {"name": "echo", "locale": "multilingual", "gender": "male"},
            {"name": "fable", "locale": "multilingual", "gender": "neutral"},
            {"name": "onyx", "locale": "multilingual", "gender": "male"},
            {"name": "nova", "locale": "multilingual", "gender": "female"},
            {"name": "shimmer", "locale": "multilingual", "gender": "female"},
        ]
