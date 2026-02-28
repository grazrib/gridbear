"""Tests for core.plugin_registry.PluginRegistry."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from core.plugin_registry import PluginRegistry

# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def registry():
    """Fresh PluginRegistry instance."""
    return PluginRegistry()


@pytest.fixture
def config_path(tmp_path):
    """Temporary plugins.json path."""
    return tmp_path / "plugins.json"


def _make_entry(
    name,
    state="available",
    enabled=False,
    manifest_hash="",
    entry_id=None,
):
    """Helper to build a dict resembling a PluginRegistryEntry row."""
    return {
        "id": entry_id or hash(name),
        "name": name,
        "state": state,
        "enabled": enabled,
        "version": "1.0",
        "plugin_type": "service",
        "manifest_hash": manifest_hash,
    }


# ── Static helpers (no DB mocking) ───────────────────────────────────


class TestManifestHash:
    def test_manifest_hash_deterministic(self):
        manifest = {"name": "test", "version": "1.0"}
        h1 = PluginRegistry._manifest_hash(manifest)
        h2 = PluginRegistry._manifest_hash(manifest)
        assert h1 == h2

    def test_manifest_hash_changes_on_content(self):
        m1 = {"name": "alpha", "version": "1.0"}
        m2 = {"name": "alpha", "version": "2.0"}
        assert PluginRegistry._manifest_hash(m1) != PluginRegistry._manifest_hash(m2)

    def test_manifest_hash_length(self):
        h = PluginRegistry._manifest_hash({"name": "x"})
        assert len(h) == 16


class TestCreateDefaultConfigDB:
    """Tests for _create_default_config_db (writes defaults to DB)."""

    async def test_creates_defaults_from_schema(self):
        manifest = {
            "config_schema": {
                "properties": {
                    "api_url": {"type": "string", "default": "http://localhost"},
                    "timeout": {"type": "integer", "default": 30},
                }
            }
        }

        with patch("core.plugin_registry.registry.PluginRegistryEntry") as MockEntry:
            MockEntry.get = AsyncMock(return_value={"id": 1, "config": None})
            MockEntry.write = AsyncMock()

            await PluginRegistry._create_default_config_db(1, "my_plugin", manifest)

        MockEntry.write.assert_called_once_with(
            1, config={"api_url": "http://localhost", "timeout": 30}
        )

    async def test_skips_secrets(self):
        manifest = {
            "config_schema": {
                "properties": {
                    "api_key": {"type": "secret", "env": "MY_API_KEY"},
                    "debug": {"type": "boolean", "default": False},
                }
            }
        }

        with patch("core.plugin_registry.registry.PluginRegistryEntry") as MockEntry:
            MockEntry.get = AsyncMock(return_value={"id": 1, "config": None})
            MockEntry.write = AsyncMock()

            await PluginRegistry._create_default_config_db(1, "plugin_s", manifest)

        call_kwargs = MockEntry.write.call_args
        written_config = call_kwargs.kwargs.get("config") or call_kwargs[1].get(
            "config"
        )
        assert "api_key" not in written_config
        assert written_config["debug"] is False

    async def test_noop_if_empty_schema(self):
        manifest = {"config_schema": {"properties": {}}}

        with patch("core.plugin_registry.registry.PluginRegistryEntry") as MockEntry:
            MockEntry.get = AsyncMock()
            MockEntry.write = AsyncMock()

            await PluginRegistry._create_default_config_db(1, "empty", manifest)

        MockEntry.write.assert_not_called()

    async def test_noop_if_no_schema(self):
        manifest = {"name": "bare"}

        with patch("core.plugin_registry.registry.PluginRegistryEntry") as MockEntry:
            MockEntry.get = AsyncMock()
            MockEntry.write = AsyncMock()

            await PluginRegistry._create_default_config_db(1, "bare", manifest)

        MockEntry.write.assert_not_called()

    async def test_preserves_existing_config(self):
        """Does not overwrite if entry already has config."""
        manifest = {
            "config_schema": {
                "properties": {
                    "host": {"type": "string", "default": "0.0.0.0"},
                }
            }
        }

        with patch("core.plugin_registry.registry.PluginRegistryEntry") as MockEntry:
            MockEntry.get = AsyncMock(
                return_value={"id": 1, "config": {"host": "custom"}}
            )
            MockEntry.write = AsyncMock()

            await PluginRegistry._create_default_config_db(1, "svc", manifest)

        MockEntry.write.assert_not_called()


# ── Async tests (mock PluginRegistryEntry) ────────────────────────────


class TestSyncWithDisk:
    async def test_sync_new_plugin_inserted_as_available(self, registry):
        with patch("core.plugin_registry.registry.PluginRegistryEntry") as MockEntry:
            MockEntry.search = AsyncMock(return_value=[])
            MockEntry.create = AsyncMock()

            disk = {
                "telegram": {"name": "telegram", "type": "channel", "version": "2.0"}
            }
            await registry.sync_with_disk(disk)

            MockEntry.create.assert_called_once()
            call_kwargs = MockEntry.create.call_args.kwargs
            assert call_kwargs["name"] == "telegram"
            assert call_kwargs["state"] == "available"
            assert call_kwargs["enabled"] is False

    async def test_sync_missing_plugin_marked_not_available(self, registry):
        existing = _make_entry("removed_plugin", state="installed", entry_id=42)
        with patch("core.plugin_registry.registry.PluginRegistryEntry") as MockEntry:
            MockEntry.search = AsyncMock(return_value=[existing])
            MockEntry.write = AsyncMock()

            await registry.sync_with_disk({})  # disk is empty

            MockEntry.write.assert_called_once_with(
                42, state="not_available", enabled=False
            )

    async def test_sync_restored_plugin(self, registry):
        existing = _make_entry(
            "restored", state="not_available", manifest_hash="old", entry_id=7
        )
        manifest = {"name": "restored", "type": "service", "version": "1.0"}

        with patch("core.plugin_registry.registry.PluginRegistryEntry") as MockEntry:
            MockEntry.search = AsyncMock(return_value=[existing])
            MockEntry.write = AsyncMock()

            await registry.sync_with_disk({"restored": manifest})

            MockEntry.write.assert_called_once()
            call_kwargs = MockEntry.write.call_args.kwargs
            assert call_kwargs["state"] == "available"

    async def test_sync_manifest_updated(self, registry):
        old_hash = PluginRegistry._manifest_hash({"version": "1.0"})
        existing = _make_entry(
            "updated", state="installed", manifest_hash=old_hash, entry_id=9
        )
        new_manifest = {"version": "2.0", "type": "service"}

        with patch("core.plugin_registry.registry.PluginRegistryEntry") as MockEntry:
            MockEntry.search = AsyncMock(return_value=[existing])
            MockEntry.write = AsyncMock()

            await registry.sync_with_disk({"updated": new_manifest})

            MockEntry.write.assert_called_once()
            call_kwargs = MockEntry.write.call_args
            assert call_kwargs.kwargs["version"] == "2.0"
            new_hash = PluginRegistry._manifest_hash(new_manifest)
            assert call_kwargs.kwargs["manifest_hash"] == new_hash


class TestMigrateFromConfig:
    async def test_migrate_from_config_populates_db(self, registry, config_path):
        config_path.write_text(
            json.dumps({"enabled": ["telegram", "memory"], "other_key": True})
        )
        disk = {
            "telegram": {"type": "channel", "version": "1.0"},
            "memory": {"type": "service", "version": "1.0"},
            "unused": {"type": "service", "version": "0.1"},
        }

        with patch("core.plugin_registry.registry.PluginRegistryEntry") as MockEntry:
            MockEntry.count = AsyncMock(return_value=0)
            MockEntry.create = AsyncMock()
            MockEntry.raw_execute = AsyncMock()

            result = await registry.migrate_from_config(config_path, disk)

        assert result is True
        # 2 enabled + 1 available = 3 creates
        assert MockEntry.create.call_count == 3

        # Verify 'enabled' key kept for backward compatibility
        data = json.loads(config_path.read_text())
        assert "enabled" in data
        assert data["other_key"] is True

    async def test_migrate_skipped_if_db_populated(self, registry, config_path):
        config_path.write_text(json.dumps({"enabled": ["telegram"]}))

        with patch("core.plugin_registry.registry.PluginRegistryEntry") as MockEntry:
            MockEntry.count = AsyncMock(return_value=5)

            result = await registry.migrate_from_config(config_path, {})

        assert result is False


class TestInstall:
    async def test_install_creates_config_and_sets_state(self, registry):
        entry = _make_entry("my_svc", state="available", entry_id=10)
        manifest = {
            "config_schema": {
                "properties": {
                    "url": {"type": "string", "default": "http://localhost"},
                }
            }
        }

        with patch("core.plugin_registry.registry.PluginRegistryEntry") as MockEntry:
            MockEntry.get = AsyncMock(
                side_effect=[
                    entry,  # First call from install()
                    {
                        "id": 10,
                        "config": None,
                    },  # Second call from _create_default_config_db
                ]
            )
            MockEntry.write = AsyncMock()
            MockEntry.raw_execute = AsyncMock()

            warnings = await registry.install("my_svc", manifest)

        assert warnings == []
        # write called twice: once for config defaults, once for state
        assert MockEntry.write.call_count == 2
        # Second write sets state=installed
        MockEntry.write.assert_any_call(10, state="installed")

    async def test_install_rejects_wrong_state(self, registry):
        entry = _make_entry("already", state="installed", entry_id=11)

        with patch("core.plugin_registry.registry.PluginRegistryEntry") as MockEntry:
            MockEntry.get = AsyncMock(return_value=entry)

            with pytest.raises(ValueError, match="expected 'available'"):
                await registry.install("already", {})


class TestUninstall:
    async def test_uninstall_resets_state(self, registry):
        entry = _make_entry("target_plugin", state="installed", entry_id=20)

        with (
            patch("core.plugin_registry.registry.PluginRegistryEntry") as MockEntry,
            patch.object(PluginRegistry, "_cleanup_secrets", return_value=None),
            patch.object(PluginRegistry, "_cleanup_data_dir", return_value=None),
        ):
            MockEntry.get = AsyncMock(return_value=entry)
            MockEntry.write = AsyncMock()
            MockEntry.raw_execute = AsyncMock()

            await registry.uninstall("target_plugin")

        # write called twice: clear config + reset state
        assert MockEntry.write.call_count == 2
        MockEntry.write.assert_any_call(20, config={})
        MockEntry.write.assert_any_call(20, state="available", enabled=False)

    async def test_uninstall_not_available_deletes_entry(self, registry):
        """Purging a not_available plugin removes it from the DB entirely."""
        entry = _make_entry("gone_plugin", state="not_available", entry_id=21)

        with (
            patch("core.plugin_registry.registry.PluginRegistryEntry") as MockEntry,
            patch.object(PluginRegistry, "_cleanup_secrets", return_value=None),
            patch.object(PluginRegistry, "_cleanup_data_dir", return_value=None),
        ):
            MockEntry.get = AsyncMock(return_value=entry)
            MockEntry.write = AsyncMock()
            MockEntry.delete = AsyncMock()

            await registry.uninstall("gone_plugin")

        # config cleared, then entry deleted (not written back)
        MockEntry.write.assert_called_once_with(21, config={})
        MockEntry.delete.assert_called_once_with(21)


class TestSetEnabled:
    async def test_set_enabled_validates_deps(self, registry):
        entry = _make_entry("child", state="installed", entry_id=30)
        manifest = {"dependencies": {"required": ["parent"]}}
        dep_entry = _make_entry("parent", state="available", enabled=False, entry_id=31)

        with (
            patch("core.plugin_registry.registry.PluginRegistryEntry") as MockEntry,
            patch.object(PluginRegistry, "_load_manifest", return_value=manifest),
        ):
            MockEntry.get = AsyncMock(
                side_effect=lambda name: {
                    "child": entry,
                    "parent": dep_entry,
                }.get(name)
            )

            with pytest.raises(ValueError, match="not installed/enabled"):
                await registry.set_enabled("child", True)

    async def test_set_enabled_succeeds_when_deps_met(self, registry):
        entry = _make_entry("child", state="installed", entry_id=30)
        manifest = {"dependencies": {"required": ["parent"]}}
        dep_entry = _make_entry("parent", state="installed", enabled=True, entry_id=31)

        with (
            patch("core.plugin_registry.registry.PluginRegistryEntry") as MockEntry,
            patch.object(PluginRegistry, "_load_manifest", return_value=manifest),
        ):
            MockEntry.get = AsyncMock(
                side_effect=lambda name: {
                    "child": entry,
                    "parent": dep_entry,
                }.get(name)
            )
            MockEntry.write = AsyncMock()

            await registry.set_enabled("child", True)

            MockEntry.write.assert_called_once_with(30, enabled=True)

    async def test_disable_skips_dep_validation(self, registry):
        entry = _make_entry("plugin", state="installed", entry_id=40)

        with patch("core.plugin_registry.registry.PluginRegistryEntry") as MockEntry:
            MockEntry.get = AsyncMock(return_value=entry)
            MockEntry.write = AsyncMock()

            await registry.set_enabled("plugin", False)

            MockEntry.write.assert_called_once_with(40, enabled=False)


class TestGetEnabledPlugins:
    async def test_get_enabled_plugins(self, registry):
        rows = [
            _make_entry("alpha", state="installed", enabled=True),
            _make_entry("beta", state="installed", enabled=True),
        ]
        with patch("core.plugin_registry.registry.PluginRegistryEntry") as MockEntry:
            MockEntry.search = AsyncMock(return_value=rows)

            result = await registry.get_enabled_plugins()

        assert result == ["alpha", "beta"]
        MockEntry.search.assert_called_once_with(
            [("state", "=", "installed"), ("enabled", "=", True)],
            order="name",
        )

    async def test_get_enabled_plugins_empty(self, registry):
        with patch("core.plugin_registry.registry.PluginRegistryEntry") as MockEntry:
            MockEntry.search = AsyncMock(return_value=[])

            result = await registry.get_enabled_plugins()

        assert result == []
