"""Tests for PluginPathResolver and multi-directory plugin support."""

import json
import os
from pathlib import Path
from unittest.mock import patch

from core.plugin_paths import PluginPathResolver, build_plugin_dirs


def _make_plugin(base_dir: Path, name: str, manifest: dict | None = None):
    """Helper: create a plugin dir with manifest.json."""
    plugin_dir = base_dir / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    manifest = manifest or {"name": name, "type": "service"}
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest))
    return plugin_dir


class TestPluginPathResolver:
    """Tests for PluginPathResolver."""

    def test_single_directory(self, tmp_path):
        """Should discover plugins from a single directory."""
        plugins = tmp_path / "plugins"
        plugins.mkdir()
        _make_plugin(plugins, "telegram", {"name": "Telegram", "type": "channel"})
        _make_plugin(plugins, "memory", {"name": "Memory", "type": "service"})

        resolver = PluginPathResolver([plugins])

        assert resolver.resolve("telegram") == plugins / "telegram"
        assert resolver.resolve("memory") == plugins / "memory"
        assert resolver.resolve("nonexistent") is None

    def test_multiple_directories(self, tmp_path):
        """Should discover plugins from multiple directories."""
        dir_a = tmp_path / "base"
        dir_b = tmp_path / "extra"
        dir_a.mkdir()
        dir_b.mkdir()
        _make_plugin(dir_a, "telegram")
        _make_plugin(dir_b, "premium-tool")

        resolver = PluginPathResolver([dir_a, dir_b])

        assert resolver.resolve("telegram") == dir_a / "telegram"
        assert resolver.resolve("premium-tool") == dir_b / "premium-tool"
        assert len(resolver.dirs) == 2

    def test_first_directory_wins_on_conflict(self, tmp_path):
        """First directory should win when both have a plugin with the same name."""
        dir_a = tmp_path / "ce"
        dir_b = tmp_path / "ee"
        dir_a.mkdir()
        dir_b.mkdir()
        _make_plugin(dir_a, "shared-plugin", {"name": "CE version", "type": "service"})
        _make_plugin(dir_b, "shared-plugin", {"name": "EE version", "type": "service"})

        resolver = PluginPathResolver([dir_a, dir_b])

        assert resolver.resolve("shared-plugin") == dir_a / "shared-plugin"
        manifests = resolver.discover_all()
        assert manifests["shared-plugin"]["name"] == "CE version"

    def test_discover_all(self, tmp_path):
        """discover_all should return manifests from all directories."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        _make_plugin(dir_a, "plugin-a", {"name": "A", "type": "channel"})
        _make_plugin(dir_b, "plugin-b", {"name": "B", "type": "mcp"})

        resolver = PluginPathResolver([dir_a, dir_b])
        manifests = resolver.discover_all()

        assert len(manifests) == 2
        assert manifests["plugin-a"]["name"] == "A"
        assert manifests["plugin-b"]["name"] == "B"

    def test_iter_all_dirs(self, tmp_path):
        """iter_all_dirs should yield all plugin subdirectories, skip duplicates."""
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        _make_plugin(dir_a, "plugin-1")
        _make_plugin(dir_a, "plugin-2")
        _make_plugin(dir_b, "plugin-3")
        _make_plugin(dir_b, "plugin-2")  # duplicate — should be skipped

        resolver = PluginPathResolver([dir_a, dir_b])
        dirs = list(resolver.iter_all_dirs())

        names = [d.name for d in dirs]
        assert sorted(names) == ["plugin-1", "plugin-2", "plugin-3"]
        # plugin-2 should come from dir_a (first wins)
        p2 = [d for d in dirs if d.name == "plugin-2"][0]
        assert p2.parent == dir_a

    def test_skips_nonexistent_directory(self, tmp_path):
        """Non-existent directories should be silently skipped."""
        existing = tmp_path / "existing"
        existing.mkdir()
        _make_plugin(existing, "my-plugin")

        resolver = PluginPathResolver([existing, tmp_path / "missing"])

        assert len(resolver.dirs) == 1
        assert resolver.resolve("my-plugin") == existing / "my-plugin"

    def test_skips_dirs_without_manifest(self, tmp_path):
        """Directories without manifest.json should be ignored."""
        plugins = tmp_path / "plugins"
        plugins.mkdir()
        _make_plugin(plugins, "valid")
        # dir without manifest
        (plugins / "no-manifest").mkdir()

        resolver = PluginPathResolver([plugins])

        assert resolver.resolve("valid") is not None
        assert resolver.resolve("no-manifest") is None

    def test_skips_files_not_dirs(self, tmp_path):
        """Regular files in the plugins directory should be ignored."""
        plugins = tmp_path / "plugins"
        plugins.mkdir()
        _make_plugin(plugins, "real-plugin")
        (plugins / "README.md").write_text("hello")

        resolver = PluginPathResolver([plugins])

        assert len(resolver.discover_all()) == 1

    def test_rebuild_cache(self, tmp_path):
        """rebuild_cache should pick up new plugins added at runtime."""
        plugins = tmp_path / "plugins"
        plugins.mkdir()
        _make_plugin(plugins, "existing")

        resolver = PluginPathResolver([plugins])
        assert resolver.resolve("new-plugin") is None

        _make_plugin(plugins, "new-plugin")
        resolver.rebuild_cache()

        assert resolver.resolve("new-plugin") == plugins / "new-plugin"

    def test_invalid_manifest_json(self, tmp_path):
        """Plugin with invalid JSON manifest should be skipped."""
        plugins = tmp_path / "plugins"
        plugins.mkdir()
        bad_dir = plugins / "bad-json"
        bad_dir.mkdir()
        (bad_dir / "manifest.json").write_text("{invalid json")
        _make_plugin(plugins, "good")

        resolver = PluginPathResolver([plugins])

        assert resolver.resolve("bad-json") is None
        assert resolver.resolve("good") is not None

    def test_dirs_property_returns_copy(self, tmp_path):
        """dirs property should return a copy, not a reference."""
        plugins = tmp_path / "plugins"
        plugins.mkdir()

        resolver = PluginPathResolver([plugins])
        dirs = resolver.dirs
        dirs.append(tmp_path / "injected")

        assert len(resolver.dirs) == 1

    def test_empty_directories_list(self):
        """Empty list of directories should work without errors."""
        resolver = PluginPathResolver([])

        assert resolver.resolve("anything") is None
        assert resolver.discover_all() == {}
        assert list(resolver.iter_all_dirs()) == []
        assert resolver.dirs == []


class TestBuildPluginDirs:
    """Tests for build_plugin_dirs helper."""

    def test_default_without_env(self, tmp_path):
        """Without EXTRA_PLUGINS_DIRS, should return only base_dir/plugins."""
        (tmp_path / "plugins").mkdir()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EXTRA_PLUGINS_DIRS", None)
            dirs = build_plugin_dirs(tmp_path)

        assert len(dirs) == 1
        assert dirs[0] == tmp_path / "plugins"

    def test_with_extra_dirs(self, tmp_path):
        """EXTRA_PLUGINS_DIRS should add extra directories."""
        (tmp_path / "plugins").mkdir()
        extra = tmp_path / "ee-plugins"
        extra.mkdir()

        with patch.dict(os.environ, {"EXTRA_PLUGINS_DIRS": str(extra)}):
            dirs = build_plugin_dirs(tmp_path)

        assert len(dirs) == 2
        assert dirs[0] == tmp_path / "plugins"
        assert dirs[1] == extra

    def test_colon_separated_extra_dirs(self, tmp_path):
        """Multiple directories separated by colons should all be included."""
        (tmp_path / "plugins").mkdir()
        ee = tmp_path / "ee"
        ee.mkdir()
        community = tmp_path / "community"
        community.mkdir()

        env_val = f"{ee}:{community}"
        with patch.dict(os.environ, {"EXTRA_PLUGINS_DIRS": env_val}):
            dirs = build_plugin_dirs(tmp_path)

        assert len(dirs) == 3
        assert dirs[1] == ee
        assert dirs[2] == community

    def test_nonexistent_extra_dir_skipped(self, tmp_path):
        """Non-existent extra directories should be silently skipped."""
        (tmp_path / "plugins").mkdir()

        with patch.dict(
            os.environ,
            {"EXTRA_PLUGINS_DIRS": "/nonexistent/path"},
        ):
            dirs = build_plugin_dirs(tmp_path)

        assert len(dirs) == 1

    def test_empty_env_var(self, tmp_path):
        """Empty EXTRA_PLUGINS_DIRS should behave like unset."""
        (tmp_path / "plugins").mkdir()

        with patch.dict(os.environ, {"EXTRA_PLUGINS_DIRS": ""}):
            dirs = build_plugin_dirs(tmp_path)

        assert len(dirs) == 1

    def test_trailing_colons_ignored(self, tmp_path):
        """Trailing/leading colons in EXTRA_PLUGINS_DIRS should be handled."""
        (tmp_path / "plugins").mkdir()
        ee = tmp_path / "ee"
        ee.mkdir()

        with patch.dict(os.environ, {"EXTRA_PLUGINS_DIRS": f":{ee}:"}):
            dirs = build_plugin_dirs(tmp_path)

        assert len(dirs) == 2
        assert dirs[1] == ee

    def test_base_plugins_always_first(self, tmp_path):
        """base_dir/plugins should always be first regardless of extras."""
        (tmp_path / "plugins").mkdir()
        first = tmp_path / "first"
        first.mkdir()

        with patch.dict(os.environ, {"EXTRA_PLUGINS_DIRS": str(first)}):
            dirs = build_plugin_dirs(tmp_path)

        assert dirs[0] == tmp_path / "plugins"


class TestGetPluginPath:
    """Tests for get_plugin_path from core.registry."""

    def test_with_resolver(self, tmp_path):
        """Should use resolver when available."""
        import core.registry as reg

        plugins = tmp_path / "plugins"
        plugins.mkdir()
        _make_plugin(plugins, "telegram")

        resolver = PluginPathResolver([plugins])
        original = reg._path_resolver
        try:
            reg._path_resolver = resolver
            result = reg.get_plugin_path("telegram")
            assert result == plugins / "telegram"
        finally:
            reg._path_resolver = original

    def test_without_resolver_fallback(self, tmp_path):
        """Without resolver, should fall back to BASE_DIR/plugins/name."""
        import core.registry as reg

        original = reg._path_resolver
        try:
            reg._path_resolver = None
            with patch("config.settings.BASE_DIR", tmp_path):
                plugins = tmp_path / "plugins"
                plugins.mkdir()
                (plugins / "test-plugin").mkdir()
                (plugins / "test-plugin" / "manifest.json").write_text("{}")

                result = reg.get_plugin_path("test-plugin")
                assert result == plugins / "test-plugin"
        finally:
            reg._path_resolver = original

    def test_without_resolver_missing_plugin(self, tmp_path):
        """Without resolver, missing plugin should return None."""
        import core.registry as reg

        original = reg._path_resolver
        try:
            reg._path_resolver = None
            with patch("config.settings.BASE_DIR", tmp_path):
                (tmp_path / "plugins").mkdir()
                result = reg.get_plugin_path("nonexistent")
                assert result is None
        finally:
            reg._path_resolver = original
