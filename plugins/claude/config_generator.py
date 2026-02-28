"""Generate Claude CLI config files on startup.

With named Docker volumes (instead of bind mounts), the config files
(settings.local.json, .claude.json) need to be generated inside the
container at startup. This module handles that generation.

settings.local.json: permissions from SystemConfig 'claude_settings'
.claude.json: project config (allowedTools, mcpServers) read from
              .claude.container.json and merged with existing auth data
              (oauthAccount) to avoid overwriting login state.
"""

import json
from pathlib import Path

from config.logging_config import logger
from config.settings import BASE_DIR

CLAUDE_HOME = Path.home() / ".claude"
SETTINGS_PATH = CLAUDE_HOME / "settings.local.json"
CLAUDE_JSON_PATH = Path.home() / ".claude.json"
CONTAINER_JSON = BASE_DIR / ".claude.container.json"

# Default project config when no .claude.container.json exists
_DEFAULT_PROJECTS = {
    "/app": {
        "allowedTools": ["Bash", "Read", "Write", "Edit"],
        "hasTrustDialogAccepted": True,
    }
}


def generate_settings_local() -> bool:
    """Write settings.local.json from SystemConfig claude_settings.

    Returns True if the file was written or already up to date.
    """
    from core.system_config import SystemConfig

    source_data = SystemConfig.get_param_sync("claude_settings")
    if not source_data:
        logger.debug(
            "No claude_settings in SystemConfig — skipping settings.local.json"
        )
        return False

    CLAUDE_HOME.mkdir(parents=True, exist_ok=True)

    # Only write if content changed
    if SETTINGS_PATH.exists():
        try:
            existing = json.loads(SETTINGS_PATH.read_text())
            if existing == source_data:
                return True
        except (json.JSONDecodeError, OSError):
            pass

    SETTINGS_PATH.write_text(json.dumps(source_data, indent=2) + "\n")
    logger.info("Generated %s", SETTINGS_PATH)
    return True


def _load_project_config() -> dict:
    """Load project config from .claude.container.json.

    Reads the `projects` section from the repo-level config file.
    Falls back to minimal defaults if the file doesn't exist.
    """
    if CONTAINER_JSON.exists():
        try:
            data = json.loads(CONTAINER_JSON.read_text())
            projects = data.get("projects")
            if projects:
                logger.debug(
                    "Loaded %d project configs from %s",
                    len(projects),
                    CONTAINER_JSON,
                )
                return projects
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Cannot read %s: %s", CONTAINER_JSON, e)

    return _DEFAULT_PROJECTS


def generate_claude_json(project_config: dict | None = None) -> bool:
    """Merge project config into .claude.json without overwriting auth data.

    The .claude.json file contains both project config (allowedTools, mcpServers)
    and auth/cache data (oauthAccount, userID, etc.) that is managed by
    ``claude auth login``. This function always updates the ``projects`` section
    from .claude.container.json while preserving all other keys.

    Args:
        project_config: Override project config dict. If None, reads from
            .claude.container.json or uses minimal defaults.
    """
    # Load existing .claude.json (may contain oauthAccount, caches, etc.)
    existing = {}
    if CLAUDE_JSON_PATH.exists():
        try:
            existing = json.loads(CLAUDE_JSON_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    # Determine project config source
    new_projects = (
        project_config if project_config is not None else _load_project_config()
    )

    # Skip write if projects haven't changed
    if existing.get("projects") == new_projects:
        return True

    existing["projects"] = new_projects
    CLAUDE_JSON_PATH.write_text(json.dumps(existing, indent=2) + "\n")
    logger.info(
        "Updated %s — %d project(s), auth data %s",
        CLAUDE_JSON_PATH,
        len(new_projects),
        "preserved" if "oauthAccount" in existing else "absent",
    )
    return True


def generate_all():
    """Run all config generation steps."""
    generate_settings_local()
    generate_claude_json()
