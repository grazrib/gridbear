"""Text-to-Speech Service using Edge TTS (Microsoft voices)."""

import uuid
from pathlib import Path

import edge_tts

from config.logging_config import logger
from core.interfaces.service import BaseTTSService


class TTSService(BaseTTSService):
    """TTS service using Microsoft Edge voices (free)."""

    name = "tts"

    def __init__(self, config: dict):
        self.config = config
        self.default_voice = config.get("default_voice", "en-US-AriaNeural")
        self.voices = config.get(
            "voices",
            {
                "en": "en-US-AriaNeural",
                "it": "it-IT-ElsaNeural",
                "es": "es-ES-ElviraNeural",
                "fr": "fr-FR-DeniseNeural",
                "de": "de-DE-KatjaNeural",
            },
        )
        self.output_dir = Path(config.get("output_dir", "data/tts"))

    async def initialize(self) -> None:
        """Initialize TTS service."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"TTS service initialized with default voice: {self.default_voice}")

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
            voice: Voice name (e.g., "it-IT-ElsaNeural"). If None, uses locale or default.
            locale: Locale code (e.g., "it", "en"). Used to select voice if voice is None.

        Returns:
            Path to the generated audio file (MP3)
        """
        if not voice:
            if locale:
                voice = self.get_voice_for_locale(locale)
            else:
                voice = self.default_voice

        output_path = self.output_dir / f"tts_{uuid.uuid4().hex}.mp3"

        try:
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(str(output_path))
            logger.debug(f"TTS generated: {output_path} (voice: {voice})")
            return str(output_path)
        except Exception as e:
            logger.exception(f"TTS error: {e}")
            raise

    async def list_voices(self, locale: str | None = None) -> list[dict]:
        """List available voices, optionally filtered by locale.

        Args:
            locale: Filter voices by locale (e.g., "it", "en")

        Returns:
            List of voice dictionaries with name, locale, gender
        """
        voices = await edge_tts.list_voices()

        if locale:
            locale_prefix = locale.lower()
            voices = [
                v for v in voices if v["Locale"].lower().startswith(locale_prefix)
            ]

        return [
            {
                "name": v["ShortName"],
                "locale": v["Locale"],
                "gender": v["Gender"],
            }
            for v in voices
        ]
