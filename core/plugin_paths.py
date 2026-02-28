"""Plugin path resolution for multi-directory plugin support.

Centralizes plugin discovery across multiple directories (like Odoo's --addons-path).
First directory wins on name conflicts, providing deterministic override behavior.

Usage:
    resolver = PluginPathResolver(build_plugin_dirs(BASE_DIR))
    path = resolver.resolve("myplugin")  # -> Path to plugin dir
"""

import json
import os
from collections.abc import Iterator
from pathlib import Path

from config.logging_config import logger


class PluginPathResolver:
    """Resolves plugin names to filesystem paths across multiple directories.

    Maintains a name -> Path cache. When multiple directories contain a plugin
    with the same name, the first directory in the list wins (like Odoo).
    """

    def __init__(self, plugin_dirs: list[Path]):
        self._dirs = [d for d in plugin_dirs if d.exists()]
        self._cache: dict[str, Path] = {}
        self._manifest_cache: dict[str, dict] = {}
        self.rebuild_cache()

    def resolve(self, name: str) -> Path | None:
        """Resolve a plugin name to its directory path.

        Args:
            name: Plugin directory name (e.g. "myplugin", "memory")

        Returns:
            Path to plugin directory or None if not found
        """
        return self._cache.get(name)

    def discover_all(self) -> dict[str, dict]:
        """Discover all plugins across all directories.

        Returns:
            Dict mapping plugin name to manifest dict.
            First directory wins on name conflicts.
        """
        return dict(self._manifest_cache)

    def iter_all_dirs(self) -> Iterator[Path]:
        """Iterate over all plugin subdirectories across all base dirs.

        Yields individual plugin directories (e.g. plugins/myplugin/),
        not the base directories themselves. Skips non-directories and
        directories without manifest.json.
        """
        seen = set()
        for base_dir in self._dirs:
            if not base_dir.exists():
                continue
            for plugin_dir in sorted(base_dir.iterdir()):
                if not plugin_dir.is_dir():
                    continue
                name = plugin_dir.name
                if name in seen:
                    continue
                seen.add(name)
                if (plugin_dir / "manifest.json").exists():
                    yield plugin_dir

    def rebuild_cache(self) -> None:
        """Rebuild the name -> path and name -> manifest caches.

        Call after adding/removing plugins at runtime.
        """
        self._cache.clear()
        self._manifest_cache.clear()

        for base_dir in self._dirs:
            if not base_dir.exists():
                continue
            for plugin_dir in sorted(base_dir.iterdir()):
                if not plugin_dir.is_dir():
                    continue
                name = plugin_dir.name
                # First directory wins
                if name in self._cache:
                    continue
                manifest_path = plugin_dir / "manifest.json"
                if not manifest_path.exists():
                    continue
                try:
                    with open(manifest_path) as f:
                        manifest = json.load(f)
                    self._cache[name] = plugin_dir
                    self._manifest_cache[name] = manifest
                except Exception as e:
                    logger.error(f"Failed to read manifest for {name}: {e}")

        if len(self._dirs) > 1:
            logger.info(
                f"PluginPathResolver: {len(self._cache)} plugins "
                f"across {len(self._dirs)} directories"
            )

    @property
    def dirs(self) -> list[Path]:
        """List of plugin base directories (ordered by priority)."""
        return list(self._dirs)


def build_plugin_dirs(base_dir: Path) -> list[Path]:
    """Build the list of plugin directories from base_dir and env vars.

    Priority order (first directory wins on name conflicts):
    1. base_dir/plugins/ (always first, hardcoded)
    2. Paths from GRIDBEAR_PLUGIN_PATHS env var (comma-separated)
    3. Paths from EXTRA_PLUGINS_DIRS env var (colon-separated, legacy compat)

    Non-existent directories are logged and skipped.
    """
    dirs = [base_dir / "plugins"]

    # GRIDBEAR_PLUGIN_PATHS env var (primary — replaces plugins.json plugin_paths)
    gridbear_paths = os.environ.get("GRIDBEAR_PLUGIN_PATHS", "").strip()
    if gridbear_paths:
        for path_str in gridbear_paths.split(","):
            path_str = path_str.strip()
            if not path_str:
                continue
            path = Path(path_str)
            if path.exists():
                dirs.append(path)
            else:
                logger.warning(
                    f"GRIDBEAR_PLUGIN_PATHS: skipping non-existent '{path_str}'"
                )

    # EXTRA_PLUGINS_DIRS env var (legacy compat)
    extra = os.environ.get("EXTRA_PLUGINS_DIRS", "").strip()
    if extra:
        for path_str in extra.split(":"):
            path_str = path_str.strip()
            if not path_str:
                continue
            path = Path(path_str)
            if path.exists():
                dirs.append(path)
            else:
                logger.warning(
                    f"EXTRA_PLUGINS_DIRS: skipping non-existent '{path_str}'"
                )

    return dirs
