"""Text-to-Speech Service using Google Cloud TTS."""

import json
import uuid
from pathlib import Path

from google.cloud import texttospeech
from google.oauth2 import service_account

from config.logging_config import logger
from core.interfaces.service import BaseTTSService
from ui.secrets_manager import secrets_manager


class GoogleTTSService(BaseTTSService):
    """TTS service using Google Cloud Text-to-Speech."""

    name = "tts"

    def __init__(self, config: dict):
        self.config = config
        self.default_voice = config.get("default_voice", "en-US-Neural2-F")
        self.voices = config.get(
            "voices",
            {
                "en": "en-US-Neural2-F",
                "it": "it-IT-Neural2-A",
                "es": "es-ES-Neural2-A",
                "fr": "fr-FR-Neural2-A",
                "de": "de-DE-Neural2-A",
            },
        )
        self.output_dir = Path(config.get("output_dir", "data/tts"))
        self.client = None

    async def initialize(self) -> None:
        """Initialize Google Cloud TTS client."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        try:
            sa_json = secrets_manager.get_plain("GOOGLE_SERVICE_ACCOUNT")
            if sa_json:
                info = json.loads(sa_json)
                credentials = service_account.Credentials.from_service_account_info(
                    info
                )
                self.client = texttospeech.TextToSpeechClient(credentials=credentials)
            else:
                self.client = texttospeech.TextToSpeechClient()
            logger.info(
                "Google TTS service initialized with default voice: %s",
                self.default_voice,
            )
        except Exception as e:
            logger.error("Failed to initialize Google TTS: %s", e)
            raise

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
        if not self.client:
            raise RuntimeError("Google TTS client not initialized")

        if not voice:
            if locale:
                voice = self.get_voice_for_locale(locale)
            else:
                voice = self.default_voice

        # Parse voice name to get language code (e.g., "en-US-Neural2-F" -> "en-US")
        parts = voice.split("-")
        language_code = f"{parts[0]}-{parts[1]}" if len(parts) >= 2 else "en-US"

        output_path = self.output_dir / f"tts_{uuid.uuid4().hex}.mp3"

        try:
            synthesis_input = texttospeech.SynthesisInput(text=text)

            voice_params = texttospeech.VoiceSelectionParams(
                language_code=language_code,
                name=voice,
            )

            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3
            )

            response = self.client.synthesize_speech(
                input=synthesis_input,
                voice=voice_params,
                audio_config=audio_config,
            )

            with open(output_path, "wb") as out:
                out.write(response.audio_content)

            logger.debug("Google TTS generated: %s (voice: %s)", output_path, voice)
            return str(output_path)

        except Exception as e:
            logger.exception("Google TTS error: %s", e)
            raise

    async def list_voices(self, locale: str | None = None) -> list[dict]:
        """List available voices, optionally filtered by locale."""
        if not self.client:
            return []

        try:
            response = self.client.list_voices()
            voices = []

            for voice in response.voices:
                for lang in voice.language_codes:
                    if locale and not lang.lower().startswith(locale.lower()):
                        continue
                    voices.append(
                        {
                            "name": voice.name,
                            "locale": lang,
                            "gender": texttospeech.SsmlVoiceGender(
                                voice.ssml_gender
                            ).name,
                        }
                    )

            return voices
        except Exception as e:
            logger.error("Failed to list Google TTS voices: %s", e)
            return []
