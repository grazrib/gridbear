"""TTS Base Plugin.

Stub service — the actual synthesis is delegated to providers
(tts-openai, tts-edge, tts-elevenlabs, tts-google) via the
``provides: tts`` mechanism.
"""

from config.logging_config import logger
from core.interfaces.service import BaseTTSService


class TTSBaseService(BaseTTSService):
    """Base TTS service stub.

    Provider plugins (tts-openai, tts-edge, etc.) replace this at
    runtime via ``provides: tts`` in their manifest.
    """

    name = "tts"

    async def initialize(self) -> None:
        logger.info("TTS base plugin loaded (delegates to providers)")

    async def shutdown(self) -> None:
        pass

    async def synthesize(self, text: str, voice: str = "default") -> str:
        raise NotImplementedError(
            "No TTS provider active — enable a tts-* plugin "
            "(tts-openai, tts-edge, etc.)"
        )
