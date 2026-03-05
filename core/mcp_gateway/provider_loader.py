"""MCP Gateway - Provider Loader.

Discovers MCP servers from plugin registry DB + manifest.json without using PluginManager.
Lightweight enough for the admin container where PluginManager is not available.
"""

import importlib.util
import sys
import types
from dataclasses import dataclass
from pathlib import Path

from config.logging_config import logger

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _get_plugins_dir() -> Path:
    """Get primary plugins directory (backward compat for standalone usage)."""
    return BASE_DIR / "plugins"


@dataclass
class ServerInfo:
    """Information about a single MCP server."""

    server_name: str
    config: dict  # {command, args, env} or {type: "sse", url} or {type: "http", url}
    transport: str  # "stdio" | "sse" | "http"
    provider_name: str  # display name (e.g. "odoo-mcp")
    allowed_tools: list[str] | None = None  # from get_allowed_tools() if available
    user_aware: bool = False  # True if server needs per-user credentials
    service_connection_id: str | None = None  # connection ID from manifest
    plugin_dir: str | None = None  # plugin directory name (e.g. "odoo")
    category: str = "system"  # mcp_category from manifest (e.g. "erp", "communication")


def _classify_transport(config: dict) -> str:
    """Determine transport type from server config."""
    if "command" in config:
        return "stdio"
    cfg_type = config.get("type", "")
    if cfg_type == "virtual":
        return "virtual"  # handled by LocalToolProvider, no MCP server
    if cfg_type == "sse":
        return "sse"
    if cfg_type == "http":
        return "http"
    if "url" in config:
        return "sse"  # default for url-based configs
    return "stdio"


def _ensure_namespace_packages() -> None:
    """Ensure gridbear.plugins namespace exists in sys.modules for imports."""
    from core.registry import get_path_resolver

    if "gridbear" not in sys.modules:
        gridbear_pkg = types.ModuleType("gridbear")
        gridbear_pkg.__path__ = []
        gridbear_pkg.__package__ = "gridbear"
        sys.modules["gridbear"] = gridbear_pkg
    if "gridbear.plugins" not in sys.modules:
        resolver = get_path_resolver()
        plugin_dirs = (
            [str(d) for d in resolver.dirs] if resolver else [str(_get_plugins_dir())]
        )
        plugins_pkg = types.ModuleType("gridbear.plugins")
        plugins_pkg.__path__ = plugin_dirs
        plugins_pkg.__package__ = "gridbear.plugins"
        sys.modules["gridbear.plugins"] = plugins_pkg


def _load_provider_class(plugin_name: str, manifest: dict) -> type | None:
    """Import and return the provider class from a plugin.

    Uses importlib dynamic loading, same pattern as PluginManager._load_plugin().
    """
    from core.registry import get_plugin_path

    plugin_path = get_plugin_path(plugin_name) or _get_plugins_dir() / plugin_name
    entry_point = plugin_path / manifest["entry_point"]

    if not entry_point.exists():
        logger.warning(f"MCP Gateway: entry point not found: {entry_point}")
        return None

    _ensure_namespace_packages()

    module_name = f"gridbear.plugins.{plugin_name}"

    # Skip if already loaded (avoid re-execution)
    if module_name in sys.modules:
        module = sys.modules[module_name]
    else:
        spec = importlib.util.spec_from_file_location(
            module_name,
            entry_point,
            submodule_search_locations=[str(plugin_path)],
        )
        if spec is None or spec.loader is None:
            logger.warning(f"MCP Gateway: failed to load spec for {plugin_name}")
            return None

        module = importlib.util.module_from_spec(spec)
        module.__path__ = [str(plugin_path)]
        module.__package__ = module_name
        sys.modules[module_name] = module

        short_module_name = f"plugins.{plugin_name}"
        sys.modules[short_module_name] = module

        try:
            spec.loader.exec_module(module)
        except Exception as e:
            logger.error(f"MCP Gateway: failed to import {plugin_name}: {e}")
            # Clean up failed module
            sys.modules.pop(module_name, None)
            sys.modules.pop(f"plugins.{plugin_name}", None)
            return None

    class_name = manifest.get("class_name", "")
    if not hasattr(module, class_name):
        logger.warning(f"MCP Gateway: class {class_name} not found in {plugin_name}")
        return None

    return getattr(module, class_name)


def _load_enabled_plugins_from_db() -> tuple[list[str], dict[str, dict]]:
    """Load enabled plugins and their configs from DB.

    Returns (enabled_names, {name: config_dict}).
    """
    from core.plugin_registry.models import PluginRegistryEntry

    entries = PluginRegistryEntry.search_sync(
        [("state", "=", "installed"), ("enabled", "=", True)]
    )
    enabled = [e["name"] for e in entries]
    configs = {e["name"]: e.get("config") or {} for e in entries}
    return enabled, configs


def discover_mcp_servers() -> dict[str, ServerInfo]:
    """Discover all MCP servers from enabled plugins.

    Reads enabled plugins from DB registry, filters type="mcp",
    imports providers and extracts server configs.

    Returns:
        Dict mapping server_name -> ServerInfo
    """
    enabled, plugin_configs = _load_enabled_plugins_from_db()
    if not enabled:
        logger.warning("MCP Gateway: no enabled plugins found")
        return {}

    servers: dict[str, ServerInfo] = {}

    from core.registry import get_path_resolver

    resolver = get_path_resolver()
    all_manifests = resolver.discover_all() if resolver else {}

    for plugin_name in enabled:
        manifest = all_manifests.get(plugin_name)
        if manifest is None:
            continue

        # Only process MCP-type plugins
        if manifest.get("type") != "mcp":
            # Also check for service plugins with mcp_provider
            if manifest.get("type") == "service" and manifest.get("mcp_provider"):
                # Load the MCP provider from service plugin
                _discover_service_mcp_provider(
                    plugin_name, manifest, plugin_configs, servers
                )
            continue

        plugin_config = plugin_configs.get(plugin_name, {})

        try:
            provider_cls = _load_provider_class(plugin_name, manifest)
            if provider_cls is None:
                continue

            provider = provider_cls(plugin_config)

            server_config = provider.get_server_config()
            if not server_config:
                continue

            # Get allowed_tools if the provider supports it
            allowed_tools = None
            if hasattr(provider, "get_allowed_tools"):
                allowed_tools = provider.get_allowed_tools()

            # Plugins with service_connections (e.g. Odoo OAuth2) are
            # user_aware: the gateway needs per-user credentials to connect.
            svc_conns = manifest.get("service_connections", [])
            is_user_aware = len(svc_conns) > 0
            svc_conn_id = svc_conns[0]["id"] if svc_conns else None

            # Use provider.name for server naming (matches plugin_manager behavior)
            display_name = getattr(provider, "name", plugin_name) or plugin_name

            # Read mcp_category from manifest (defaults to "system")
            mcp_category = manifest.get("mcp_category", "system")

            # Determine if single server or multi-server
            _expand_server_config(
                server_config,
                display_name,
                allowed_tools,
                servers,
                user_aware=is_user_aware,
                service_connection_id=svc_conn_id,
                plugin_dir=plugin_name,
                category=mcp_category,
            )

        except Exception as e:
            logger.error(f"MCP Gateway: failed to load provider {plugin_name}: {e}")
            continue

    logger.info(
        f"MCP Gateway: discovered {len(servers)} servers from "
        f"{len(enabled)} enabled plugins"
    )
    return servers


def _discover_service_mcp_provider(
    plugin_name: str,
    manifest: dict,
    config: dict,
    servers: dict[str, ServerInfo],
) -> None:
    """Discover MCP servers from a service plugin's mcp_provider."""
    provider_file = manifest.get("mcp_provider")
    provider_class_name = manifest.get("mcp_provider_class")
    if not provider_file or not provider_class_name:
        return

    from core.registry import get_plugin_path

    plugin_path = get_plugin_path(plugin_name) or _get_plugins_dir() / plugin_name
    provider_path = plugin_path / provider_file
    if not provider_path.exists():
        return

    _ensure_namespace_packages()

    module_name = f"gridbear.plugins.{plugin_name}.mcp_provider"
    if module_name in sys.modules:
        provider_module = sys.modules[module_name]
    else:
        try:
            spec = importlib.util.spec_from_file_location(module_name, provider_path)
            if spec is None or spec.loader is None:
                return

            provider_module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = provider_module
            spec.loader.exec_module(provider_module)
        except Exception as e:
            logger.error(
                f"MCP Gateway: failed to import mcp_provider from {plugin_name}: {e}"
            )
            sys.modules.pop(module_name, None)
            return

    if not hasattr(provider_module, provider_class_name):
        return

    try:
        provider_cls = getattr(provider_module, provider_class_name)
        plugin_config = config.get(plugin_name, {})
        provider = provider_cls(plugin_config)

        server_config = provider.get_server_config()
        if not server_config:
            return

        allowed_tools = None
        if hasattr(provider, "get_allowed_tools"):
            allowed_tools = provider.get_allowed_tools()

        display_name = getattr(provider, "name", plugin_name) or plugin_name

        # Detect user_aware from manifest service_connections
        svc_conns = manifest.get("service_connections", [])
        is_user_aware = len(svc_conns) > 0
        svc_conn_id = svc_conns[0]["id"] if svc_conns else None

        mcp_category = manifest.get("mcp_category", "system")

        _expand_server_config(
            server_config,
            display_name,
            allowed_tools,
            servers,
            user_aware=is_user_aware,
            service_connection_id=svc_conn_id,
            plugin_dir=plugin_name,
            category=mcp_category,
        )
    except Exception as e:
        logger.error(
            f"MCP Gateway: failed to load service mcp_provider {plugin_name}: {e}"
        )


def _expand_server_config(
    server_config: dict,
    provider_name: str,
    allowed_tools: list[str] | None,
    servers: dict[str, ServerInfo],
    user_aware: bool = False,
    service_connection_id: str | None = None,
    plugin_dir: str | None = None,
    category: str = "system",
) -> None:
    """Expand server config (single or multi-server) into ServerInfo entries.

    Handles two patterns:
    - Single server: {"command": ..., "args": ...} or {"type": "sse", "url": ...}
    - Multi server: {"server-name-1": {config}, "server-name-2": {config}}
    """
    if _is_single_server_config(server_config):
        # Single server - use provider name as server name
        transport = _classify_transport(server_config)
        if transport == "virtual":
            return  # handled by LocalToolProvider, no MCP server to connect
        servers[provider_name] = ServerInfo(
            server_name=provider_name,
            config=server_config,
            transport=transport,
            provider_name=provider_name,
            allowed_tools=allowed_tools,
            user_aware=user_aware,
            service_connection_id=service_connection_id,
            plugin_dir=plugin_dir,
            category=category,
        )
    else:
        # Multi-server (e.g. gmail-user@example.com, gws-user@example.com)
        for server_name, single_config in server_config.items():
            if not isinstance(single_config, dict):
                continue
            transport = _classify_transport(single_config)
            servers[server_name] = ServerInfo(
                server_name=server_name,
                config=single_config,
                transport=transport,
                provider_name=provider_name,
                allowed_tools=allowed_tools,
                user_aware=user_aware,
                service_connection_id=service_connection_id,
                plugin_dir=plugin_dir,
                category=category,
            )


def _is_single_server_config(config: dict) -> bool:
    """Check if config is a single server config vs multi-server dict."""
    # Single server configs have known keys
    return bool("command" in config or "url" in config or "type" in config)


if __name__ == "__main__":
    # Standalone test: python -m core.mcp_gateway.provider_loader
    import sys

    sys.path.insert(0, str(BASE_DIR))

    servers = discover_mcp_servers()
    for name, info in sorted(servers.items()):
        logger.info(
            "  %s: transport=%s, provider=%s, allowed_tools=%s",
            name,
            info.transport,
            info.provider_name,
            len(info.allowed_tools) if info.allowed_tools else "all",
        )
