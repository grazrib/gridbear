"""Plugin state registry backed by PostgreSQL."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from config.logging_config import logger
from core.plugin_registry.models import PluginRegistryEntry


class PluginRegistry:
    """PostgreSQL-backed plugin state registry.

    Source of truth for which plugins are available, installed, and enabled.
    Replaces the `enabled` array previously stored in plugins.json.
    """

    # ── Sync with disk ────────────────────────────────────────────

    async def sync_with_disk(self, disk_plugins: dict[str, dict]) -> None:
        """Compare plugins on disk vs DB, update states.

        - New on disk → insert as 'available'
        - Was not_available, now back on disk → restore previous state
          (installed if it had installed_at, otherwise available)
        - Manifest hash changed → update metadata (preserve state)
        - In DB but gone from disk → mark 'not_available'
        """
        db_entries = await PluginRegistryEntry.search([])
        db_map = {row["name"]: row for row in db_entries}

        for name, manifest in disk_plugins.items():
            m_hash = self._manifest_hash(manifest)
            plugin_type = manifest.get("type", "")
            version = manifest.get("version", "")

            if name not in db_map:
                await PluginRegistryEntry.create(
                    name=name,
                    state="available",
                    enabled=False,
                    version=version,
                    plugin_type=plugin_type,
                    manifest_hash=m_hash,
                )
                logger.info(f"Plugin registry: new plugin '{name}' (available)")

            elif db_map[name]["state"] == "not_available":
                # Restore to previous state: if it was installed before
                # (has installed_at), restore as installed+enabled so a
                # temporary volume unmount doesn't permanently downgrade.
                was_installed = db_map[name].get("installed_at") is not None
                restored_state = "installed" if was_installed else "available"
                restore_enabled = was_installed or db_map[name].get("enabled", False)
                await PluginRegistryEntry.write(
                    db_map[name]["id"],
                    state=restored_state,
                    enabled=restore_enabled,
                    version=version,
                    plugin_type=plugin_type,
                    manifest_hash=m_hash,
                )
                logger.info(
                    f"Plugin registry: '{name}' back on disk ({restored_state})"
                )

            elif m_hash != db_map[name].get("manifest_hash"):
                await PluginRegistryEntry.write(
                    db_map[name]["id"],
                    version=version,
                    plugin_type=plugin_type,
                    manifest_hash=m_hash,
                )
                logger.debug(f"Plugin registry: '{name}' manifest updated")

        for name, row in db_map.items():
            if name not in disk_plugins and row["state"] != "not_available":
                await PluginRegistryEntry.write(
                    row["id"],
                    state="not_available",
                    enabled=False,
                )
                logger.warning(
                    f"Plugin registry: '{name}' no longer on disk (not_available)"
                )

    # ── Queries ───────────────────────────────────────────────────

    async def get_all(self) -> list[dict]:
        return await PluginRegistryEntry.search([], order="name")

    async def get_state(self, name: str) -> dict | None:
        return await PluginRegistryEntry.get(name=name)

    async def get_enabled_plugins(self) -> list[str]:
        rows = await PluginRegistryEntry.search(
            [("state", "=", "installed"), ("enabled", "=", True)],
            order="name",
        )
        return [row["name"] for row in rows]

    # ── Install ───────────────────────────────────────────────────

    async def install(
        self, name: str, manifest: dict, config_path: Path | None = None
    ) -> list[str]:
        """Install: validate deps, create config defaults, set state=installed.

        Returns list of warning strings.
        Raises ValueError on invalid state or missing required deps.
        """
        entry = await PluginRegistryEntry.get(name=name)
        if not entry:
            raise ValueError(f"Plugin '{name}' not found in registry")
        if entry["state"] != "available":
            raise ValueError(
                f"Plugin '{name}' state is '{entry['state']}', expected 'available'"
            )

        warnings = []

        # Check required plugin dependencies
        raw_deps = manifest.get("dependencies", [])
        if isinstance(raw_deps, list):
            required_deps = raw_deps
        elif isinstance(raw_deps, dict):
            required_deps = raw_deps.get("required", [])
        else:
            required_deps = []

        for dep in required_deps:
            dep_entry = await PluginRegistryEntry.get(name=dep)
            if not dep_entry or dep_entry["state"] == "not_available":
                # Check if it's likely a pip package, not a plugin
                if "." in dep or dep.startswith("python-"):
                    warnings.append(f"Python package '{dep}' may need pip install")
                    continue
                raise ValueError(f"Required dependency '{dep}' not available on disk")

        # Check optional deps
        if isinstance(raw_deps, dict):
            for dep in raw_deps.get("optional", []):
                dep_entry = await PluginRegistryEntry.get(name=dep)
                if not dep_entry or dep_entry["state"] not in (
                    "installed",
                    "available",
                ):
                    warnings.append(f"Optional dependency '{dep}' not installed")

        # Create default config in DB
        await self._create_default_config_db(entry["id"], name, manifest)

        # Update DB state
        await PluginRegistryEntry.write(entry["id"], state="installed")
        await PluginRegistryEntry.raw_execute(
            "UPDATE {table} SET installed_at = NOW() WHERE name = %s", (name,)
        )

        logger.info(f"Plugin '{name}' installed")
        return warnings

    # ── Uninstall ─────────────────────────────────────────────────

    async def uninstall(self, name: str, config_path: Path | None = None) -> None:
        """Uninstall: remove config, secrets, data dir; reset state."""
        entry = await PluginRegistryEntry.get(name=name)
        if not entry:
            raise ValueError(f"Plugin '{name}' not found in registry")
        if entry["state"] not in ("installed", "not_available"):
            raise ValueError(
                f"Plugin '{name}' state is '{entry['state']}', cannot uninstall"
            )

        # Clear config in DB
        await PluginRegistryEntry.write(entry["id"], config={})

        # Remove secrets from manifest config_schema
        self._cleanup_secrets(name)

        # Remove data directory
        self._cleanup_data_dir(name)

        # Update DB
        if entry["state"] == "not_available":
            # Plugin no longer on disk — delete the registry entry entirely
            await PluginRegistryEntry.delete(entry["id"])
            logger.info(f"Plugin '{name}' purged from registry (was not_available)")
        else:
            await PluginRegistryEntry.write(
                entry["id"], state="available", enabled=False
            )
            await PluginRegistryEntry.raw_execute(
                "UPDATE {table} SET installed_at = NULL WHERE name = %s", (name,)
            )
            logger.info(f"Plugin '{name}' uninstalled")

    # ── Enable / Disable ──────────────────────────────────────────

    async def set_enabled(self, name: str, enabled: bool) -> None:
        entry = await PluginRegistryEntry.get(name=name)
        if not entry:
            raise ValueError(f"Plugin '{name}' not found in registry")
        if entry["state"] != "installed":
            raise ValueError(
                f"Plugin '{name}' state is '{entry['state']}', must be 'installed'"
            )

        if enabled:
            # Validate required deps are installed AND enabled
            manifest = self._load_manifest(name)
            if manifest:
                raw_deps = manifest.get("dependencies", [])
                required_deps = (
                    raw_deps
                    if isinstance(raw_deps, list)
                    else raw_deps.get("required", [])
                    if isinstance(raw_deps, dict)
                    else []
                )
                for dep in required_deps:
                    dep_entry = await PluginRegistryEntry.get(name=dep)
                    if not dep_entry:
                        continue  # likely a pip package
                    if dep_entry["state"] != "installed" or not dep_entry["enabled"]:
                        raise ValueError(
                            f"Required dependency '{dep}' is not installed/enabled"
                        )

        await PluginRegistryEntry.write(entry["id"], enabled=enabled)
        logger.info(f"Plugin '{name}' {'enabled' if enabled else 'disabled'}")

    # ── Migration ─────────────────────────────────────────────────

    async def migrate_from_config(
        self, config_path: Path, disk_plugins: dict[str, dict]
    ) -> bool:
        """One-time migration: move enabled array from plugins.json to DB.

        Also migrates per-plugin config and global settings if plugins.json
        exists. Returns True if migration ran, False if skipped.
        """
        count = await PluginRegistryEntry.count()
        if count > 0:
            return False

        if not config_path.exists():
            return False
        with open(config_path) as f:
            config = json.load(f)
        enabled_list = config.get("enabled")
        if not enabled_list:
            return False

        logger.info(
            f"Migrating {len(enabled_list)} enabled plugins from config to DB..."
        )

        # Insert enabled plugins as installed+enabled (with config)
        for name in enabled_list:
            manifest = disk_plugins.get(name, {})
            m_hash = self._manifest_hash(manifest) if manifest else ""
            plugin_config = config.get(name, {})
            await PluginRegistryEntry.create(
                name=name,
                state="installed",
                enabled=True,
                version=manifest.get("version", ""),
                plugin_type=manifest.get("type", ""),
                manifest_hash=m_hash,
                config=plugin_config,
            )
        await PluginRegistryEntry.raw_execute(
            "UPDATE {table} SET installed_at = NOW() WHERE state = 'installed'"
        )

        # Insert remaining disk plugins as available (with any config they may have)
        for name, manifest in disk_plugins.items():
            if name in enabled_list:
                continue
            plugin_config = config.get(name, {})
            await PluginRegistryEntry.create(
                name=name,
                state="available",
                enabled=False,
                version=manifest.get("version", ""),
                plugin_type=manifest.get("type", ""),
                manifest_hash=self._manifest_hash(manifest),
                config=plugin_config,
            )

        # Migrate global settings to SystemConfig
        await self._migrate_global_settings(config)

        logger.info("Migration complete: plugin states + config copied to DB")
        return True

    async def migrate_config_from_file(self, config_path: Path) -> bool:
        """Migrate per-plugin config and global settings from plugins.json to DB.

        Idempotent: checks SystemConfig for a migration marker before running.
        Called separately from migrate_from_config() to handle the case where
        registry entries already exist but config hasn't been migrated yet.

        Returns True if migration ran, False if skipped.
        """
        from core.system_config import SystemConfig

        # Check migration marker
        marker = await SystemConfig.get_param("_migration_config_from_file")
        if marker:
            return False

        if not config_path.exists():
            # No file to migrate — mark as done
            await SystemConfig.set_param("_migration_config_from_file", True)
            return False

        try:
            with open(config_path) as f:
                config = json.load(f)
        except (json.JSONDecodeError, IOError) as exc:
            logger.error(f"Failed to read plugins.json for migration: {exc}")
            return False

        logger.info("Migrating plugin config from plugins.json to DB...")

        # 1. Per-plugin config → PluginRegistryEntry.config JSONB
        system_keys = {
            "enabled",
            "default_runner",
            "active_theme",
            "plugin_paths",
            "mcp_gateway",
        }
        migrated_count = 0
        for key, value in config.items():
            if key in system_keys:
                continue
            if not isinstance(value, dict):
                continue
            entry = await PluginRegistryEntry.get(name=key)
            if entry and not entry.get("config"):
                await PluginRegistryEntry.write(entry["id"], config=value)
                migrated_count += 1

        # 2. Global settings → SystemConfig
        await self._migrate_global_settings(config)

        # 3. plugin_paths → log instruction for .env
        plugin_paths = config.get("plugin_paths", [])
        if plugin_paths:
            paths_str = ",".join(plugin_paths)
            logger.warning(
                "plugin_paths found in plugins.json. "
                "Add to .env: GRIDBEAR_PLUGIN_PATHS=%s",
                paths_str,
            )

        # 4. Mark migration done
        await SystemConfig.set_param("_migration_config_from_file", True)

        # 5. Rename file to .migrated (safety: keep the data)
        migrated_path = config_path.with_suffix(".json.migrated")
        try:
            config_path.rename(migrated_path)
            logger.info(
                "Renamed %s → %s",
                config_path.name,
                migrated_path.name,
            )
        except OSError as exc:
            logger.warning("Could not rename plugins.json to .migrated: %s", exc)

        logger.info(
            "Config migration complete: %d plugin configs, global settings moved to DB",
            migrated_count,
        )
        return True

    @staticmethod
    async def _migrate_global_settings(config: dict) -> None:
        """Migrate global settings from parsed plugins.json to SystemConfig."""
        from core.system_config import SystemConfig

        global_keys = {
            "default_runner": config.get("default_runner"),
            "active_theme": config.get("active_theme"),
            "mcp_gateway": config.get("mcp_gateway"),
        }
        for key, value in global_keys.items():
            if value is not None:
                await SystemConfig.set_param(key, value)

    # ── Private helpers ───────────────────────────────────────────

    @staticmethod
    def _manifest_hash(manifest: dict) -> str:
        raw = json.dumps(manifest, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @staticmethod
    def _load_manifest(name: str) -> dict | None:
        from core.registry import get_path_resolver

        resolver = get_path_resolver()
        if not resolver:
            return None
        path = resolver.resolve(name)
        if not path:
            return None
        manifest_path = path / "manifest.json"
        if not manifest_path.exists():
            return None
        with open(manifest_path) as f:
            return json.load(f)

    @staticmethod
    async def _create_default_config_db(
        entry_id: int, name: str, manifest: dict
    ) -> None:
        """Create default config from manifest config_schema into DB."""
        config_schema = manifest.get("config_schema", {})
        default_config = {}
        properties = config_schema.get("properties", config_schema)
        for key, schema in properties.items():
            if key in (
                "type",
                "properties",
                "definitions",
                "required",
                "$schema",
            ):
                continue
            if not isinstance(schema, dict):
                continue
            if schema.get("type") != "secret":
                default_config[key] = schema.get("default", "")

        if not default_config:
            return

        # Only set defaults if no config exists yet
        entry = await PluginRegistryEntry.get(id=entry_id)
        if entry and not entry.get("config"):
            await PluginRegistryEntry.write(entry_id, config=default_config)

    @staticmethod
    def _cleanup_secrets(name: str) -> None:
        try:
            from ui.secrets_manager import secrets_manager

            manifest = PluginRegistry._load_manifest(name)
            if not manifest:
                return
            config_schema = manifest.get("config_schema", {})
            properties = config_schema.get("properties", config_schema)
            for key, schema in properties.items():
                if isinstance(schema, dict) and schema.get("type") == "secret":
                    env_key = schema.get("env", key.upper())
                    secrets_manager.delete(env_key)
        except Exception as exc:
            logger.warning(f"Could not clean secrets for '{name}': {exc}")

    @staticmethod
    def _cleanup_data_dir(name: str) -> None:
        try:
            from config.settings import BASE_DIR

            data_dir = BASE_DIR / "data" / name
            if data_dir.exists() and data_dir.is_dir():
                import shutil

                shutil.rmtree(data_dir, ignore_errors=True)
                logger.info(f"Removed data directory: {data_dir}")
        except Exception as exc:
            logger.warning(f"Could not remove data dir for '{name}': {exc}")
