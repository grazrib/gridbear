"""Shared helpers for plugin admin routes.

Centralises manifest loading, dependency parsing, template context
building, and plugin config I/O so every plugin route file doesn't
duplicate the same boilerplate.
"""

import json
from pathlib import Path

from fastapi import Request

from config.logging_config import logger


def get_plugin_metadata(plugin_dir: Path) -> dict:
    """Load manifest and return metadata dict for admin template sidebar.

    Handles both legacy array deps and new dict {required, optional} format.
    """
    manifest_path = plugin_dir / "manifest.json"
    if not manifest_path.exists():
        return {}

    with open(manifest_path) as f:
        manifest = json.load(f)

    raw_deps = manifest.get("dependencies", [])
    if isinstance(raw_deps, list):
        deps = {"required": raw_deps, "optional": []}
    elif isinstance(raw_deps, dict):
        deps = {
            "required": raw_deps.get("required", []),
            "optional": raw_deps.get("optional", []),
        }
    else:
        deps = {"required": [], "optional": []}

    dependents = []
    try:
        from core.registry import get_plugin_manager

        pm = get_plugin_manager()
        if pm:
            dep_info = pm.get_dependents(plugin_dir.name)
            dependents = dep_info.get("required_by", []) + dep_info.get(
                "optional_by", []
            )
    except Exception:
        pass

    display_name = manifest.get("ui", {}).get("display_name") or manifest.get(
        "name", plugin_dir.name
    )

    return {
        "plugin": {
            "display_name": display_name,
            "version": manifest.get("version", "1.0.0"),
            "type": manifest.get("type", "unknown"),
            "provides": manifest.get("provides"),
            "description": manifest.get("description", ""),
            "model": manifest.get("model"),
        },
        "plugin_name": plugin_dir.name,
        "plugin_dependencies": deps,
        "plugin_dependents": dependents,
    }


def get_plugin_template_context(request: Request, plugin_dir: Path, **kwargs) -> dict:
    """Build base template context for a plugin admin page.

    Merges request, empty plugin-type lists, plugin metadata from
    manifest, and any page-specific kwargs.
    """
    plugin_menus = getattr(request.state, "plugin_menus", [])
    return {
        "request": request,
        "plugin_menus": plugin_menus,
        "enabled_channels": [],
        "enabled_services": [],
        "enabled_mcp": [],
        "enabled_runners": [],
        "plugin_health": {},
        **get_plugin_metadata(plugin_dir),
        **kwargs,
    }


# -- Enabled plugins (PostgreSQL-backed) -----------------------------------


def get_enabled_plugins() -> list[str]:
    """Get list of enabled plugin names from DB registry."""
    try:
        from core.plugin_registry.models import PluginRegistryEntry

        entries = PluginRegistryEntry.search_sync(
            [("state", "=", "installed"), ("enabled", "=", True)],
            order="name",
        )
        return [e["name"] for e in entries]
    except Exception as exc:
        logger.debug("get_enabled_plugins from DB failed: %s", exc)
    return []


# -- Plugin config helpers (PostgreSQL-backed) -----------------------------


def load_plugin_config(plugin_name: str) -> dict:
    """Load a plugin's config from the DB (PluginRegistryEntry.config JSONB)."""
    try:
        from core.plugin_registry.models import PluginRegistryEntry

        entry = PluginRegistryEntry.get_sync(name=plugin_name)
        if entry:
            return entry.get("config") or {}
    except Exception as exc:
        logger.debug("load_plugin_config(%s) DB failed: %s", plugin_name, exc)
    return {}


def save_plugin_config(plugin_name: str, config: dict) -> None:
    """Save a plugin's config to the DB (PluginRegistryEntry.config JSONB)."""
    try:
        from core.plugin_registry.models import PluginRegistryEntry

        entry = PluginRegistryEntry.get_sync(name=plugin_name)
        if entry:
            PluginRegistryEntry.write_sync(entry["id"], config=config)
        else:
            logger.warning(
                "save_plugin_config: plugin '%s' not in registry", plugin_name
            )
    except Exception as exc:
        logger.error("save_plugin_config(%s) failed: %s", plugin_name, exc)
