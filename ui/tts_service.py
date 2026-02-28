"""TTS adapter for WebChat.

Loads TTS plugin classes dynamically via importlib to synthesize speech
server-side. Falls back to browser (returns None) when provider is 'browser'.

TTS providers are discovered from plugin manifests with "provides": "tts".
"""

import importlib.util

from config.logging_config import logger

_instances: dict[str, object] = {}


def _discover_tts_plugins() -> dict[str, dict]:
    """Discover TTS plugins from manifests with 'provides': 'tts'.

    Returns dict of provider_name -> {dir_name, display_name, manifest}.
    """
    from core.registry import get_path_resolver
    from ui.plugin_helpers import get_enabled_plugins

    result = {}
    resolver = get_path_resolver()
    enabled = get_enabled_plugins()
    all_manifests = resolver.discover_all() if resolver else {}

    for plugin_name in enabled:
        manifest = all_manifests.get(plugin_name)
        if manifest is None:
            continue
        try:
            if manifest.get("provides") == "tts":
                result[plugin_name] = {
                    "dir_name": plugin_name,
                    "display_name": manifest.get("display_name", plugin_name),
                    "manifest": manifest,
                }
        except Exception:
            continue

    return result


def _load_class(provider: str):
    """Load a TTS plugin class via importlib (handles hyphenated dirs)."""
    from core.registry import get_plugin_path

    tts_plugins = _discover_tts_plugins()
    if provider not in tts_plugins:
        raise ValueError(f"TTS provider '{provider}' not found")

    info = tts_plugins[provider]
    dir_name = info["dir_name"]
    manifest = info["manifest"]
    plugin_dir = get_plugin_path(dir_name)
    if plugin_dir is None:
        raise ValueError(f"TTS provider '{provider}' directory not found")

    class_name = manifest["class_name"]
    entry_point = manifest.get("entry_point", "service.py")
    module_path = plugin_dir / entry_point

    spec = importlib.util.spec_from_file_location(
        f"tts_plugin_{dir_name.replace('-', '_')}", module_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, class_name)


def _get_plugin_config(provider: str) -> dict:
    """Read plugin config from DB."""
    from ui.plugin_helpers import load_plugin_config

    return load_plugin_config(provider)


async def _get_instance(provider: str):
    """Get or create a singleton TTS service instance."""
    if provider in _instances:
        return _instances[provider]

    cls = _load_class(provider)
    config = _get_plugin_config(provider)
    instance = cls(config)
    await instance.initialize()
    _instances[provider] = instance
    logger.info(f"WebChat TTS: initialized {provider}")
    return instance


async def synthesize(text: str, provider: str, locale: str = "it") -> str | None:
    """Synthesize text to speech.

    Returns file path to MP3, or None if provider is 'browser'.
    """
    if provider == "browser":
        return None

    tts_plugins = _discover_tts_plugins()
    if provider not in tts_plugins:
        return None

    instance = await _get_instance(provider)
    return await instance.synthesize(text, locale=locale)


def get_available_providers() -> list[dict]:
    """Return list of available TTS providers with metadata.

    Dynamically discovers TTS plugins from manifests with "provides": "tts".
    """
    providers = [
        {"id": "browser", "name": "Browser (Web Speech API)", "requires_key": False},
    ]

    for provider_id, info in _discover_tts_plugins().items():
        manifest = info["manifest"]
        config_schema = manifest.get("config_schema", {})
        requires_key = any(
            v.get("type") == "secret"
            for v in config_schema.values()
            if isinstance(v, dict)
        )
        providers.append(
            {
                "id": provider_id,
                "name": info["display_name"],
                "requires_key": requires_key,
            }
        )

    return providers


def clear_cache():
    """Clear cached TTS instances (call when provider setting changes)."""
    _instances.clear()
