"""Provider discovery for base plugins (image, tts).

Scans enabled plugin manifests for those that declare ``provides: <base>``
and returns their config/secrets info for unified admin pages.
"""

import os

from ui.plugin_helpers import (
    get_enabled_plugins,
    load_plugin_config,
    save_plugin_config,
)
from ui.secrets_manager import secrets_manager


def discover_providers(provides_name: str) -> list[dict]:
    """Find all enabled provider plugins for a given base.

    Args:
        provides_name: The base plugin name (e.g. ``"image"``, ``"tts"``).

    Returns:
        List of dicts, each with:
        - name, display_name, description, version
        - config_schema, current_config, secrets_status
    """
    from core.registry import get_path_resolver

    resolver = get_path_resolver()
    if not resolver:
        return []

    all_manifests = resolver.discover_all()
    enabled = get_enabled_plugins()
    providers = []

    for plugin_name in enabled:
        manifest = all_manifests.get(plugin_name)
        if not manifest:
            continue
        if manifest.get("provides") != provides_name:
            continue

        config_schema = manifest.get("config_schema", {})
        current_config = load_plugin_config(plugin_name)

        # Merge config with schema defaults, separate secrets
        merged_config = {}
        secrets_status = {}
        schema_props = config_schema.get("properties", config_schema)

        for key, schema in schema_props.items():
            if key in ("type", "properties", "definitions", "required", "$schema"):
                continue
            if not isinstance(schema, dict):
                continue
            if schema.get("type") == "secret":
                env_key = schema.get("env", key.upper())
                if secrets_manager.is_available() and secrets_manager.exists(env_key):
                    secrets_status[env_key] = "encrypted"
                elif os.getenv(env_key):
                    secrets_status[env_key] = "env"
                else:
                    secrets_status[env_key] = "missing"
            else:
                default_value = schema.get("default", "")
                merged_config[key] = current_config.get(key, default_value)

        providers.append(
            {
                "name": plugin_name,
                "display_name": manifest.get("display_name", plugin_name),
                "description": manifest.get("description", ""),
                "version": manifest.get("version", "0.0.1"),
                "config_schema": config_schema,
                "current_config": merged_config,
                "secrets_status": secrets_status,
            }
        )

    # Sort alphabetically by display name
    providers.sort(key=lambda p: p["display_name"])
    return providers


def save_provider_config(provider_name: str, new_config: dict) -> None:
    """Save a provider plugin's configuration section."""
    save_plugin_config(provider_name, new_config)
