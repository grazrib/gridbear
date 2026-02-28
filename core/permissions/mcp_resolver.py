"""Unified MCP permission resolver.

Single source of truth for MCP permission logic:
expand user/group permissions, match wildcards, filter tools.
"""

from __future__ import annotations

from config.logging_config import logger
from config.settings import (
    get_group_permissions,
    get_unified_user_id,
    get_user_mcp_permissions,
)


def resolve_permissions(
    username: str | None,
    platform: str,
    is_group_chat: bool = False,
    unified_id: str | None = None,
    agent_mcp_permissions: list[str] | None = None,
    extra_servers: list[str] | None = None,
) -> list[str]:
    """Build the full MCP permission list for a request.

    Pipeline: base perms → user intersection → group perms → extra servers → private_only filter.

    When both agent and user permissions exist, uses intersection:
    the user can only access tools that BOTH the agent AND the user are allowed.
    """
    expanded: set[str] = set()

    # 1. Base permissions: agent-level, user-level, or intersection
    user_perms = get_user_mcp_permissions(username) if username else None

    if agent_mcp_permissions is not None and user_perms is not None:
        # Both configured: intersection (user can only use agent tools they're allowed)
        for agent_perm in agent_mcp_permissions:
            if matches_permission(agent_perm, user_perms):
                expanded.add(agent_perm)
    elif agent_mcp_permissions is not None:
        # Only agent configured: use agent permissions
        expanded.update(agent_mcp_permissions)
    elif user_perms is not None:
        # Only user configured: use user permissions
        expanded.update(user_perms)
    # else: neither configured, expanded stays empty

    # 2. Group permissions (by unified_id)
    if username:
        uid = unified_id or get_unified_user_id(platform, username)
        group_perms = get_group_permissions(uid)
        expanded.update(group_perms)

        # 3. Extra MCP servers (e.g. shared accounts expanded by caller)
        if extra_servers:
            expanded.update(extra_servers)

    # 4. Filter private_only servers in group chats
    if is_group_chat:
        return filter_private_only(list(expanded))

    return list(expanded)


def matches_permission(server_name: str, allowed_servers: list[str]) -> bool:
    """Check if server_name matches any permission in allowed_servers.

    Supports:
        - Exact match: "myserver" matches "myserver"
        - Wildcard suffix: "mail-*" matches "mail-user@example.com"
        - Wildcard all: "*" matches everything
    """
    for permission in allowed_servers:
        if permission == "*":
            return True
        if permission.endswith("-*"):
            prefix = permission[:-1]  # "gmail-*" -> "gmail-"
            if server_name.startswith(prefix):
                return True
        elif permission == server_name:
            return True
    return False


def check_tool_permission(
    tool_name: str,
    permissions: list[str],
    sanitized_to_original: dict[str, str] | None = None,
    ns_sep: str = "__",
) -> bool:
    """Check if a single tool call is authorized by the permission list.

    Non-namespaced tools (internal tools like gridbear_help) are always allowed.
    For namespaced MCP tools, extracts the server prefix and checks against permissions.
    """
    if ns_sep not in tool_name:
        return True  # Internal tools are always allowed
    sanitized = tool_name[: tool_name.index(ns_sep)]
    original = (sanitized_to_original or {}).get(sanitized, sanitized)
    return matches_permission(original, permissions)


def filter_tools_by_permissions(
    tools: list[dict],
    permissions: list[str],
    sanitized_to_original: dict[str, str] | None = None,
    ns_sep: str = "__",
) -> list[dict]:
    """Filter a tool list by MCP permissions.

    Each tool name is namespaced as "sanitized_server__tool_name".
    Permission matching checks against original server names.
    """
    reverse_map = sanitized_to_original or {}

    filtered = []
    for tool in tools:
        name = tool.get("name", "")
        if ns_sep in name:
            sanitized = name[: name.index(ns_sep)]
            original = reverse_map.get(sanitized, sanitized)
            if matches_permission(original, permissions):
                filtered.append(tool)
        else:
            if "*" in permissions:
                filtered.append(tool)
    return filtered


def filter_private_only(
    permissions: list[str],
    private_only_servers: set[str] | None = None,
) -> list[str]:
    """Remove private_only MCP servers from the permission list."""
    if private_only_servers is None:
        from core.registry import get_plugin_manager

        pm = get_plugin_manager()
        if pm is None:
            return permissions
        private_only_servers = pm.get_private_only_servers()

    if not private_only_servers:
        return permissions

    filtered = [
        p for p in permissions if not _matches_private_server(p, private_only_servers)
    ]
    if len(filtered) < len(permissions):
        removed = set(permissions) - set(filtered)
        logger.info(f"Group chat: filtered private_only MCP servers: {removed}")
    return filtered


def _matches_private_server(perm: str, private_servers: set[str]) -> bool:
    """Check if a permission matches any private_only server."""
    for server in private_servers:
        if perm == server or perm.startswith(f"{server}-"):
            return True
    return False
