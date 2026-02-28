"""Transcription Base Plugin.

Delegates audio transcription to the configured default provider
(transcription-openai, transcription-assemblyai, etc.).

Unlike image/tts stubs, this service is called directly by channel
adapters for voice message handling, so it must delegate at runtime.
"""

import importlib.util
import json
from pathlib import Path

from config.logging_config import logger
from core.interfaces.service import BaseTranscriptionService

PLUGINS_DIR = Path(__file__).resolve().parent.parent


def _load_provider_class(provider_name: str):
    """Load a transcription provider class by plugin name."""
    plugin_dir = PLUGINS_DIR / provider_name
    manifest_path = plugin_dir / "manifest.json"
    if not manifest_path.exists():
        return None

    manifest = json.loads(manifest_path.read_text())
    if manifest.get("provides", manifest.get("type")) != "transcription":
        return None

    class_name = manifest.get("class_name")
    entry_point = manifest.get("entry_point", "service.py")
    if not class_name:
        return None

    service_path = plugin_dir / entry_point
    if not service_path.exists():
        return None

    spec = importlib.util.spec_from_file_location(
        f"gridbear.plugins.{provider_name}.service",
        service_path,
        submodule_search_locations=[str(service_path.parent)],
    )
    if spec is None or spec.loader is None:
        return None

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, class_name, None)


def _get_provider_config(provider_name: str) -> dict:
    """Read provider config from DB."""
    try:
        from core.plugin_registry.models import PluginRegistryEntry

        entry = PluginRegistryEntry.get_sync(name=provider_name)
        if entry:
            return entry.get("config") or {}
    except Exception:
        pass
    return {}


class TranscriptionBaseService(BaseTranscriptionService):
    """Base transcription service that delegates to the default provider.

    Channel adapters call ``get_service("transcription").transcribe()``
    for voice messages, so this must actually instantiate and delegate
    to the configured provider (unlike the image/tts stubs).
    """

    name = "transcription"

    def __init__(self, config: dict):
        super().__init__(config)
        self._delegate: BaseTranscriptionService | None = None

    async def initialize(self) -> None:
        provider_name = self.config.get("default_provider")
        if not provider_name:
            logger.info(
                "No default transcription provider configured — "
                "voice messages will not be transcribed"
            )
            return
        provider_class = _load_provider_class(provider_name)
        if not provider_class:
            logger.warning(
                "Transcription provider '%s' not found — "
                "voice messages will not be transcribed",
                provider_name,
            )
            return

        try:
            provider_config = _get_provider_config(provider_name)
            self._delegate = provider_class(provider_config)
            await self._delegate.initialize()
            logger.info("Transcription base plugin → %s", provider_name)
        except Exception:
            logger.exception(
                "Failed to initialize transcription provider '%s'", provider_name
            )
            self._delegate = None

    async def shutdown(self) -> None:
        if self._delegate:
            await self._delegate.shutdown()

    async def transcribe(self, audio_path: str, language: str | None = None) -> str:
        if not self._delegate:
            logger.error("No transcription provider available")
            return ""
        return await self._delegate.transcribe(audio_path, language)
