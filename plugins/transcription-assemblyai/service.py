"""Transcription provider using AssemblyAI with speaker diarization."""

import asyncio
from pathlib import Path

import httpx

from config.logging_config import logger
from core.interfaces.service import BaseTranscriptionService
from ui.secrets_manager import secrets_manager

ASSEMBLYAI_UPLOAD_URL = "https://api.assemblyai.com/v2/upload"
ASSEMBLYAI_TRANSCRIPT_URL = "https://api.assemblyai.com/v2/transcript"

SUPPORTED_FORMATS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".webm", ".mp4"}


class TranscriptionAssemblyAIService(BaseTranscriptionService):
    """Audio transcription using AssemblyAI."""

    name = "transcription-assemblyai"

    def __init__(self, config: dict):
        super().__init__(config)
        self.speakers = config.get("speakers", True)
        self.api_key: str | None = None
        self._headers: dict[str, str] = {}

    async def initialize(self) -> None:
        self.api_key = secrets_manager.get_plain("ASSEMBLYAI_API_KEY")
        if not self.api_key:
            logger.warning("ASSEMBLYAI_API_KEY not configured for transcription")
        else:
            self._headers = {"authorization": self.api_key}
            logger.info(
                "Transcription-assemblyai initialized (speakers=%s)", self.speakers
            )

    async def shutdown(self) -> None:
        pass

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def transcribe(self, audio_path: str, language: str | None = None) -> str:
        """Transcribe audio file via AssemblyAI.

        Args:
            audio_path: Path to audio file
            language: Language code (e.g. 'it', 'en'). None for auto-detection.

        Returns:
            Formatted transcription text (with speaker labels if diarization
            is enabled), or empty string on error.
        """
        if not self.api_key:
            logger.error("ASSEMBLYAI_API_KEY not configured")
            return ""

        path = Path(audio_path)
        if not path.exists():
            logger.error("Audio file not found: %s", audio_path)
            return ""

        if path.suffix.lower() not in SUPPORTED_FORMATS:
            logger.error(
                "Unsupported format: %s (supported: %s)",
                path.suffix,
                ", ".join(SUPPORTED_FORMATS),
            )
            return ""

        try:
            audio_url = await self._upload_file(path)
            transcript_id = await self._request_transcription(
                audio_url, self.speakers, language
            )
            result = await self._poll_transcription(transcript_id)
            return self._format_transcript(result, self.speakers)
        except Exception:
            logger.exception("AssemblyAI transcription failed for %s", audio_path)
            return ""

    async def _upload_file(self, file_path: Path) -> str:
        """Upload audio file to AssemblyAI and return the URL."""
        async with httpx.AsyncClient(timeout=300.0) as client:
            with open(file_path, "rb") as f:
                response = await client.post(
                    ASSEMBLYAI_UPLOAD_URL,
                    headers=self._headers,
                    content=f.read(),
                )
                response.raise_for_status()
                return response.json()["upload_url"]

    async def _request_transcription(
        self,
        audio_url: str,
        speakers: bool = True,
        language: str | None = None,
    ) -> str:
        """Request transcription and return the transcript ID."""
        data: dict = {
            "audio_url": audio_url,
            "speaker_labels": speakers,
        }
        if language:
            data["language_code"] = language

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                ASSEMBLYAI_TRANSCRIPT_URL,
                headers=self._headers,
                json=data,
            )
            response.raise_for_status()
            return response.json()["id"]

    async def _poll_transcription(self, transcript_id: str) -> dict:
        """Poll for transcription completion."""
        url = f"{ASSEMBLYAI_TRANSCRIPT_URL}/{transcript_id}"

        async with httpx.AsyncClient(timeout=60.0) as client:
            while True:
                response = await client.get(url, headers=self._headers)
                response.raise_for_status()
                result = response.json()

                status = result["status"]
                if status == "completed":
                    return result
                elif status == "error":
                    raise ValueError(
                        "Transcription failed: %s"
                        % result.get("error", "Unknown error")
                    )

                await asyncio.sleep(3)

    @staticmethod
    def _format_transcript(result: dict, speakers: bool) -> str:
        """Format transcription result as readable text."""
        if not speakers or not result.get("utterances"):
            return result.get("text", "")

        lines = []
        for utterance in result["utterances"]:
            speaker = utterance.get("speaker", "?")
            start_ms = utterance.get("start", 0)
            text = utterance.get("text", "")

            minutes = start_ms // 60000
            seconds = (start_ms % 60000) // 1000
            timestamp = f"{minutes:02d}:{seconds:02d}"

            lines.append(f"Speaker {speaker} ({timestamp}): {text}")

        return "\n".join(lines)
