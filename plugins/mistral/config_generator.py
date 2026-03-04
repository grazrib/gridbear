"""Generate Vibe CLI configuration files.

Manages ~/.vibe/config.toml (model, MCP servers) and ~/.vibe/.env (API key).
Called before each CLI invocation to ensure config is current.
"""

import os
from pathlib import Path

from config.logging_config import logger

VIBE_HOME = Path.home() / ".vibe"
VIBE_CONFIG_PATH = VIBE_HOME / "config.toml"
VIBE_ENV_PATH = VIBE_HOME / ".env"


def write_env(api_key: str) -> bool:
    """Write MISTRAL_API_KEY to ~/.vibe/.env.

    Returns True if the file was written successfully.
    """
    try:
        VIBE_HOME.mkdir(parents=True, exist_ok=True)
        VIBE_ENV_PATH.write_text(f"MISTRAL_API_KEY={api_key}\n")
        return True
    except OSError as e:
        logger.warning("Could not write %s: %s", VIBE_ENV_PATH, e)
        return False


def write_config(
    model: str = "mistral-large-latest",
    gateway_url: str | None = None,
    mcp_token_env: str = "GRIDBEAR_MCP_TOKEN",
) -> bool:
    """Write ~/.vibe/config.toml with model and MCP server config.

    Args:
        model: Active model ID.
        gateway_url: MCP Gateway URL. If None, reads from MCP_GATEWAY_URL env.
        mcp_token_env: Env var name containing the MCP gateway token.

    Returns True if the file was written successfully.
    """
    gw_url = gateway_url or os.getenv("MCP_GATEWAY_URL", "http://gridbear-ui:8080")

    lines = [
        f'active_model = "{model}"',
        "",
        "[[mcp_servers]]",
        'name = "gridbear-gateway"',
        'transport = "http"',
        f'url = "{gw_url}/mcp"',
        f'api_key_env = "{mcp_token_env}"',
        'api_key_header = "Authorization"',
        'api_key_format = "Bearer {token}"',
        "",
    ]

    try:
        VIBE_HOME.mkdir(parents=True, exist_ok=True)
        VIBE_CONFIG_PATH.write_text("\n".join(lines))
        logger.debug("Wrote Vibe config: model=%s, gateway=%s", model, gw_url)
        return True
    except OSError as e:
        logger.warning("Could not write %s: %s", VIBE_CONFIG_PATH, e)
        return False


def ensure_api_key() -> bool:
    """Ensure API key is written to ~/.vibe/.env from secrets manager.

    Returns True if the API key is available and written.
    """
    from ui.secrets_manager import secrets_manager

    api_key = secrets_manager.get_plain("MISTRAL_API_KEY")
    if not api_key:
        return False
    return write_env(api_key)
