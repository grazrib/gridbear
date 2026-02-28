"""Shared theme loading utilities for the admin UI.

Provides a single point for dynamically loading theme plugin classes
via importlib, used by both jinja_env.py and routes/settings.py.
"""

import importlib.util
from pathlib import Path

from config.logging_config import logger


def load_theme_instance(
    plugin_name: str,
    manifest: dict,
    plugin_path: Path,
    theme_config: dict | None = None,
):
    """Load and instantiate a theme class from a plugin directory.

    Returns the theme instance, or None if loading fails.
    """
    entry_point = plugin_path / manifest.get("entry_point", "theme.py")
    if not entry_point.exists():
        return None

    try:
        spec = importlib.util.spec_from_file_location(
            f"_theme.{plugin_name}", entry_point
        )
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        cls = getattr(module, manifest.get("class_name", ""), None)
        if cls is None:
            return None

        return cls(theme_config or {})
    except Exception as exc:
        logger.warning("Failed to load theme %s: %s", plugin_name, exc)
        return None
