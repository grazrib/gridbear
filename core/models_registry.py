"""Centralized model registry for all runner plugins.

Stores model definitions in data/models/{runner}.json files.
Provides a single source of truth for model IDs, display names,
and API model IDs, replacing the previous triple-source approach
(manifest.json enum, runner.py available_models, api_backend MODEL_MAP).
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from config.settings import DATA_DIR

logger = logging.getLogger(__name__)

MODELS_DIR = DATA_DIR / "models"


class ModelsRegistry:
    """Registry for runner model definitions.

    Each runner gets a JSON file at data/models/{runner}.json with structure:
    {
        "models": [
            {"id": "sonnet", "name": "Sonnet", "api_id": "claude-sonnet-4-5-..."}
        ],
        "last_updated": "2026-02-15T10:00:00Z",
        "source": "manual|api|seed"
    }
    """

    def __init__(self, base_dir: Path | None = None):
        self._base_dir = base_dir or MODELS_DIR
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, runner: str) -> Path:
        return self._base_dir / f"{runner}.json"

    def _load(self, runner: str) -> dict | None:
        path = self._path(runner)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read models for %s: %s", runner, e)
            return None

    def _save(self, runner: str, data: dict) -> None:
        path = self._path(runner)
        path.write_text(json.dumps(data, indent=2) + "\n")

    def get_models(self, runner: str) -> list[dict]:
        """Return model list for a runner, or empty list if not seeded."""
        data = self._load(runner)
        if data is None:
            return []
        return data.get("models", [])

    def set_models(
        self, runner: str, models: list[dict], source: str = "manual"
    ) -> None:
        """Overwrite model list for a runner."""
        self._save(
            runner,
            {
                "models": models,
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "source": source,
            },
        )
        logger.info("Updated %d models for %s (source=%s)", len(models), runner, source)

    def get_for_ui(self, runner: str) -> list[tuple[str, str]]:
        """Return (id, display_name) tuples for UI dropdowns."""
        models = self.get_models(runner)
        if not models:
            return []
        return [(m["id"], m["name"]) for m in models]

    def get_model_map(self, runner: str) -> dict[str, str]:
        """Return {id: api_id} mapping for model resolution.

        Models without an explicit api_id use their id as the API identifier.
        """
        models = self.get_models(runner)
        return {m["id"]: m.get("api_id", m["id"]) for m in models}

    def get_metadata(self, runner: str) -> dict | None:
        """Return full data including last_updated and source."""
        return self._load(runner)

    def seed_if_empty(self, runner: str, models: list[dict]) -> bool:
        """Seed model data only if no file exists yet.

        Returns True if seeded, False if data already exists.
        """
        if self._path(runner).exists():
            return False
        self.set_models(runner, models, source="seed")
        return True
