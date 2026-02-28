"""Text-to-Speech Service using ElevenLabs."""

import uuid
from pathlib import Path

import httpx

from config.logging_config import logger
from core.interfaces.service import BaseTTSService
from ui.secrets_manager import secrets_manager


class ElevenLabsTTSService(BaseTTSService):
    """TTS service using ElevenLabs API (highest quality voices)."""

    name = "tts"

    # Default voice IDs (can use names too, will be resolved)
    DEFAULT_VOICES = {
        "Rachel": "21m00Tcm4TlvDq8ikWAM",
        "Domi": "AZnzlk1XvdvUeBnXmlld",
        "Bella": "EXAVITQu4vr4xnSDxMaL",
        "Antoni": "ErXwobaYiN019PkySvjV",
        "Elli": "MF3mGyEYCl7XYWbV9V6O",
        "Josh": "TxGEqnHWrfWFTfGW9XjX",
        "Arnold": "VR6AewLTigWG4xSOukaG",
        "Adam": "pNInz6obpgDQGcFmaJgB",
        "Sam": "yoZ06aMxZJJ28mfd3POQ",
    }

    def __init__(self, config: dict):
        self.config = config
        self.model = config.get("model", "eleven_multilingual_v2")
        self.default_voice = config.get("default_voice", "Rachel")
        self.voices = config.get(
            "voices",
            {
                "en": "Rachel",
                "it": "Rachel",
            },
        )
        self.output_dir = Path(config.get("output_dir", "data/tts"))
        self.api_key = secrets_manager.get_plain("ELEVENLABS_API_KEY")
        self._voice_cache: dict[str, str] = {}  # name -> id

    async def initialize(self) -> None:
        """Initialize ElevenLabs TTS service."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if not self.api_key:
            logger.warning("ELEVENLABS_API_KEY not set - TTS will fail")
        else:
            # Pre-fetch voice list to build name->id cache
            await self._fetch_voices()
        logger.info(
            f"ElevenLabs TTS service initialized with model: {self.model}, voice: {self.default_voice}"
        )

    async def shutdown(self) -> None:
        """Cleanup TTS service."""
        pass

    async def _fetch_voices(self) -> None:
        """Fetch available voices and cache name->id mapping."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.elevenlabs.io/v1/voices",
                    headers={"xi-api-key": self.api_key},
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()

                for voice in data.get("voices", []):
                    self._voice_cache[voice["name"]] = voice["voice_id"]

                logger.debug(f"Cached {len(self._voice_cache)} ElevenLabs voices")
        except Exception as e:
            logger.warning(f"Failed to fetch ElevenLabs voices: {e}")
            # Use defaults
            self._voice_cache = self.DEFAULT_VOICES.copy()

    def _resolve_voice_id(self, voice: str) -> str:
        """Resolve voice name to ID."""
        # If it looks like an ID (long alphanumeric), use it directly
        if len(voice) > 15 and voice.isalnum():
            return voice
        # Try cache
        if voice in self._voice_cache:
            return self._voice_cache[voice]
        # Try defaults
        if voice in self.DEFAULT_VOICES:
            return self.DEFAULT_VOICES[voice]
        # Fallback to Rachel
        return self.DEFAULT_VOICES.get("Rachel", "21m00Tcm4TlvDq8ikWAM")

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
            voice: Voice name or ID. If None, uses locale or default.
            locale: Locale code (e.g., "it", "en"). Used to select voice if voice is None.

        Returns:
            Path to the generated audio file (MP3)
        """
        if not self.api_key:
            raise RuntimeError("ELEVENLABS_API_KEY not configured")

        if not voice:
            if locale:
                voice = self.get_voice_for_locale(locale)
            else:
                voice = self.default_voice

        voice_id = self._resolve_voice_id(voice)
        output_path = self.output_dir / f"tts_{uuid.uuid4().hex}.mp3"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                    headers={
                        "xi-api-key": self.api_key,
                        "Content-Type": "application/json",
                        "Accept": "audio/mpeg",
                    },
                    json={
                        "text": text,
                        "model_id": self.model,
                        "voice_settings": {
                            "stability": 0.5,
                            "similarity_boost": 0.75,
                        },
                    },
                    timeout=60.0,
                )
                response.raise_for_status()

                with open(output_path, "wb") as f:
                    f.write(response.content)

            logger.debug(f"ElevenLabs TTS generated: {output_path} (voice: {voice})")
            return str(output_path)

        except Exception as e:
            logger.exception(f"ElevenLabs TTS error: {e}")
            raise

    async def list_voices(self, locale: str | None = None) -> list[dict]:
        """List available voices."""
        if not self._voice_cache:
            await self._fetch_voices()

        return [
            {"name": name, "locale": "multilingual", "gender": "unknown"}
            for name in self._voice_cache.keys()
        ]
