"""Tool display formatting with sensitive data filtering.

Centralizes tool name formatting and input preview logic
used by channel adapters (Telegram, Discord) for tool notifications.
"""

SENSITIVE_PREFIXES = ["mcp__secrets__", "mcp__auth__"]


def format_tool_name(tool_name: str) -> str:
    """Format raw tool name for display.

    "mcp__myserver__search" -> "myserver: search"
    """
    if tool_name.startswith("mcp__"):
        parts = tool_name.split("__")
        if len(parts) >= 3:
            return f"{parts[1]}: {parts[2]}"
    return tool_name


def is_sensitive(tool_name: str) -> bool:
    """Check if a tool handles sensitive data."""
    return any(tool_name.startswith(p) for p in SENSITIVE_PREFIXES)


DEFAULT_TOOL_ICON = "⏳"


def format_tool_status(tool_name: str, tool_input: dict, icon: str = "") -> str:
    """Format tool name + safe input preview for user-facing display.

    Returns a string like "⏳ myserver: search (res.partner)".
    Hides input details for tools matching SENSITIVE_PREFIXES.
    """
    icon = icon or DEFAULT_TOOL_ICON
    display_name = format_tool_name(tool_name)

    if is_sensitive(tool_name):
        return f"{icon} {display_name}"

    # Extract key info from input
    info = ""
    if "model" in tool_input:
        info = f" ({tool_input['model']})"
    elif "url" in tool_input:
        url = str(tool_input["url"])
        info = f" ({url[:40]}{'...' if len(url) > 40 else ''})"
    elif "query" in tool_input:
        query = str(tool_input["query"])
        info = f" ({query[:30]}{'...' if len(query) > 30 else ''})"

    return f"{icon} {display_name}{info}"


def format_grouped_status(tool_names: list[str], icon: str = "") -> str:
    """Format a group of tool calls into a single status line.

    Returns e.g. "⏳ myserver: search, read, update (3 operations)"
    """
    icon = icon or DEFAULT_TOOL_ICON
    if not tool_names:
        return ""
    if len(tool_names) == 1:
        return f"{icon} {format_tool_name(tool_names[0])}"

    display_names = [format_tool_name(n) for n in tool_names]

    # Group by server prefix if possible
    # e.g. ["myserver: search", "myserver: read"] -> "myserver: search, read"
    servers: dict[str, list[str]] = {}
    standalone: list[str] = []
    for dn in display_names:
        if ": " in dn:
            server, action = dn.split(": ", 1)
            servers.setdefault(server, []).append(action)
        else:
            standalone.append(dn)

    parts = []
    for server, actions in servers.items():
        parts.append(f"{server}: {', '.join(actions)}")
    parts.extend(standalone)

    count = len(tool_names)
    return f"{icon} {', '.join(parts)} ({count} operations)"
