"""Dynamic channel discovery for the Admin UI.

Single point of access for channel plugin metadata. Routes and templates
should never read manifests directly — use get_available_channels() and
get_channel_ui() instead.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent

CHANNEL_DEFAULTS = {
    "icon": "fas fa-comment",
    "color": "#6B7280",
    "display_name": None,  # Will use platform.capitalize()
    "badge_abbr": None,  # Will use platform[:2].upper()
}


def get_available_channels() -> list[dict]:
    """Discover all enabled channel plugins with UI metadata.

    Returns list of dicts with keys:
        name, display_name, icon, color, badge_abbr, enabled
    Uses PluginManager (runtime) with fallback to plugin registry DB + manifest (static).
    """
    channels = []

    # Try runtime PluginManager first
    try:
        from core.registry import get_plugin_manager

        pm = get_plugin_manager()
        if pm:
            for plugin_info in pm.get_plugins_by_type("channel"):
                manifest = plugin_info.get("manifest", {})
                name = manifest.get("name", plugin_info.get("name", ""))
                ui = manifest.get("ui", {})
                channels.append(_build_channel_dict(name, ui, enabled=True))
            if channels:
                return sorted(channels, key=lambda c: c["name"])
    except Exception:
        pass

    # Fallback: read enabled list from DB + manifests statically via resolver
    from core.registry import get_path_resolver
    from ui.plugin_helpers import get_enabled_plugins

    resolver = get_path_resolver()
    all_manifests = resolver.discover_all() if resolver else {}
    enabled = get_enabled_plugins()

    for plugin_name in enabled:
        manifest = all_manifests.get(plugin_name)
        if manifest is None:
            continue
        try:
            if manifest.get("type") == "channel":
                ui = manifest.get("ui", {})
                channels.append(_build_channel_dict(plugin_name, ui, enabled=True))
        except Exception:
            logger.warning("Failed to read manifest for %s", plugin_name)

    return sorted(channels, key=lambda c: c["name"])


def get_channel_ui(platform: str) -> dict:
    """Get UI metadata for a single channel (with sensible fallbacks).

    Returns dict with keys: name, display_name, icon, color, badge_abbr
    """
    # Try to find from available channels first
    for ch in get_available_channels():
        if ch["name"] == platform:
            return ch

    # Not found among enabled channels — build from manifest if exists
    from core.registry import get_plugin_path

    plugin_path = get_plugin_path(platform)
    if plugin_path:
        manifest_path = plugin_path / "manifest.json"
        if manifest_path.exists():
            try:
                with open(manifest_path) as f:
                    manifest = json.load(f)
                if manifest.get("type") == "channel":
                    return _build_channel_dict(
                        platform, manifest.get("ui", {}), enabled=False
                    )
            except Exception:
                pass

    # Complete fallback
    return _build_channel_dict(platform, {}, enabled=False)


def get_channel_ui_map() -> dict[str, dict]:
    """Get a dict mapping platform name -> UI metadata for all available channels.

    Convenient for templates that need to look up channel info by name.
    """
    return {ch["name"]: ch for ch in get_available_channels()}


def _build_channel_dict(name: str, ui: dict, enabled: bool) -> dict:
    """Build a normalized channel dict with defaults applied."""
    return {
        "name": name,
        "display_name": ui.get("display_name") or name.capitalize(),
        "icon": ui.get("icon") or CHANNEL_DEFAULTS["icon"],
        "color": ui.get("color") or CHANNEL_DEFAULTS["color"],
        "badge_abbr": ui.get("badge_abbr") or name[:2].upper(),
        "username_prefix": ui.get("username_prefix", ""),
        "enabled": enabled,
    }
