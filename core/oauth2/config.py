"""OAuth2 / MCP Gateway configuration.

Reads from SystemConfig (PostgreSQL) under the 'mcp_gateway' key.
"""

_DEFAULTS = {
    "trusted_domains": [
        "claude.ai",
        "perplexity.ai",
    ],
    "issuer": None,  # Auto-detected from request
    "access_token_expiry": 3600,
    "refresh_token_expiry": 2592000,
    "cleanup_interval_seconds": 3600,
    "db_path": "data/oauth2.db",
}


def get_gateway_config() -> dict:
    """Get MCP Gateway / OAuth2 configuration."""
    config = dict(_DEFAULTS)
    from core.system_config import SystemConfig

    gateway = SystemConfig.get_param_sync("mcp_gateway", {})
    if gateway:
        config.update(gateway)
    return config


def get_trusted_domains() -> list[str]:
    """Get list of trusted domains for auto-registration."""
    return get_gateway_config().get("trusted_domains", _DEFAULTS["trusted_domains"])


def get_db_path() -> str:
    """Get OAuth2 database path."""
    return get_gateway_config().get("db_path", _DEFAULTS["db_path"])
