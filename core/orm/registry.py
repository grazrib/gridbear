"""ORM Model registry — discovery, registration, and initialization.

At boot, the registry scans enabled plugins for ``models.py`` files,
imports them (which triggers ModelMeta registration), sorts models
by FK dependencies, and runs auto-migration.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import TYPE_CHECKING

from config.logging_config import logger
from core.orm.fields import ForeignKey
from core.orm.migrate import migrate_all
from core.orm.model import ModelMeta, set_database

if TYPE_CHECKING:
    from core.database import DatabaseManager
    from core.orm.model import Model


class Registry:
    """Central ORM model registry."""

    _models: list[type[Model]] = []
    _initialized: bool = False

    @classmethod
    def initialize(
        cls, db: DatabaseManager, plugin_dirs: list[Path] | None = None
    ) -> None:
        """Initialize the ORM: inject DB, discover models, run migrations.

        Args:
            db: The DatabaseManager instance.
            plugin_dirs: Optional list of plugin directories to scan.
                         If None, scans ``plugins/`` relative to project root.
        """
        if cls._initialized:
            logger.debug("ORM Registry already initialized, skipping")
            return

        # Inject DB reference into Model base
        set_database(db)

        # Discover and import models
        if plugin_dirs:
            for d in plugin_dirs:
                cls._scan_directory(d)
        else:
            # Auto-scan: all plugin directories via resolver + core/ + ui/
            from core.registry import get_path_resolver

            project_root = Path(__file__).parent.parent.parent
            resolver = get_path_resolver()
            if resolver:
                for d in resolver.dirs:
                    if d.exists():
                        cls._scan_directory(d)
            else:
                # Fallback when resolver not yet initialized
                plugins_dir = project_root / "plugins"
                if plugins_dir.exists():
                    cls._scan_directory(plugins_dir)
            # Also scan core/ for models (e.g. core/oauth2/models.py)
            core_dir = project_root / "core"
            if core_dir.exists():
                cls._scan_directory(core_dir)
            # Also scan ui/ for models
            admin_dir = project_root / "ui"
            if admin_dir.exists():
                cls._scan_directory(admin_dir)

        # Collect all registered models (populated by ModelMeta)
        cls._models = list(ModelMeta._all_models)
        logger.info("ORM: discovered %d models", len(cls._models))

        # Topological sort by FK dependencies
        cls._models = cls._sort_by_dependencies(cls._models)

        # Run auto-migration
        if cls._models:
            migrate_all(cls._models, db)

        cls._initialized = True

    @classmethod
    def get_models(cls) -> list[type[Model]]:
        """Return all registered models (sorted by dependency order)."""
        return list(cls._models)

    @classmethod
    def get_model(cls, schema: str, name: str) -> type[Model] | None:
        """Find a model by schema and name."""
        for m in cls._models:
            if m._schema == schema and m._name == name:
                return m
        return None

    @classmethod
    def reset(cls) -> None:
        """Reset registry state (for testing)."""
        cls._models = []
        cls._initialized = False
        ModelMeta._all_models.clear()

    @classmethod
    def _scan_directory(cls, directory: Path) -> None:
        """Scan a directory tree for models.py files and import them."""
        for models_file in directory.rglob("models.py"):
            # Skip __pycache__, .venv, etc.
            if any(p.startswith((".", "__")) for p in models_file.parts):
                continue

            # Always use file-based import to avoid triggering package
            # __init__.py side effects (some plugins have runtime imports
            # in __init__ that fail during early ORM discovery).
            cls._import_from_file(models_file)

    @classmethod
    def _file_to_module(cls, filepath: Path) -> str | None:
        """Convert a file path to a Python module path.

        Returns None if any path component is not a valid Python identifier.
        """
        project_root = Path(__file__).parent.parent.parent
        try:
            relative = filepath.relative_to(project_root)
            # Convert path to dotted module: plugins/whatsapp/models.py → plugins.whatsapp.models
            parts = list(relative.parts)
            if parts[-1].endswith(".py"):
                parts[-1] = parts[-1][:-3]
            # Reject if any part is not a valid Python identifier (e.g. hyphens)
            if not all(p.isidentifier() for p in parts):
                return None
            return ".".join(parts)
        except ValueError:
            return None

    @classmethod
    def _import_from_file(cls, filepath: Path) -> None:
        """Import a models module directly from file path.

        Uses spec_from_file_location to avoid triggering package __init__.py
        files, which may contain runtime imports that fail during early
        ORM discovery.
        """
        # Build a unique module name from the directory path
        # e.g. /app/plugins/memo/models.py -> _orm_models_plugins_memo
        parts = [p.replace("-", "_") for p in filepath.parent.parts if p and p != "/"]
        module_name = "_orm_models_" + "_".join(parts)
        try:
            spec = importlib.util.spec_from_file_location(module_name, filepath)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                logger.debug("ORM: imported %s from file %s", module_name, filepath)
        except Exception as e:
            logger.warning("ORM: failed to import %s: %s", filepath, e)

    @classmethod
    def _sort_by_dependencies(cls, models: list[type[Model]]) -> list[type[Model]]:
        """Topological sort: models with no FK deps come first."""
        model_map = {}
        for m in models:
            key = (m._schema, m._table_name)
            model_map[key] = m

        # Build adjacency: model → set of models it depends on
        deps: dict[tuple, set[tuple]] = {
            (m._schema, m._table_name): set() for m in models
        }
        for m in models:
            key = (m._schema, m._table_name)
            for fname, field in m._fields.items():
                if isinstance(field, ForeignKey) and not isinstance(field.target, str):
                    target_key = (field.target._schema, field.target._table_name)
                    if target_key in deps and target_key != key:
                        deps[key].add(target_key)

        # Kahn's algorithm
        sorted_keys = []
        no_deps = [k for k, d in deps.items() if not d]
        remaining = {k: set(d) for k, d in deps.items()}

        while no_deps:
            key = no_deps.pop(0)
            sorted_keys.append(key)
            for other, other_deps in remaining.items():
                if key in other_deps:
                    other_deps.discard(key)
                    if not other_deps and other not in sorted_keys:
                        no_deps.append(other)

        # Append any remaining (circular deps — shouldn't happen, but be safe)
        for key in deps:
            if key not in sorted_keys:
                sorted_keys.append(key)
                logger.warning("ORM: possible circular dependency for %s", key)

        return [model_map[k] for k in sorted_keys if k in model_map]
