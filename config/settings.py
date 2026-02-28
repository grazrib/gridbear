import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CREDENTIALS_DIR = BASE_DIR / "credentials"
ATTACHMENTS_DIR = DATA_DIR / "attachments"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")


def _parse_authorized_from_env(env_var: str) -> tuple[list[int], list[str]]:
    """Parse authorized users from env: returns (ids, usernames)."""
    value = os.getenv(env_var, "")
    if not value:
        return [], []
    ids = []
    usernames = []
    for item in value.split(","):
        item = item.strip().lower()
        if not item:
            continue
        if item.startswith("@"):
            item = item[1:]
        try:
            ids.append(int(item))
        except ValueError:
            usernames.append(item)
    return ids, usernames


def _get_authorized_users(platform: str) -> tuple[list[int], list[str]]:
    """Get authorized users for platform from DB, with .env fallback."""
    try:
        from core.config_models import ChannelAuthorizedUser

        rows = ChannelAuthorizedUser.search_sync([("channel", "=", platform)])
        if rows:
            ids = [r["platform_user_id"] for r in rows if r["platform_user_id"]]
            usernames = [r["username"] for r in rows if r["username"]]
            return ids, usernames
    except Exception:
        pass

    # Fallback to env
    env_var = f"{platform.upper()}_AUTHORIZED_USERS"
    return _parse_authorized_from_env(env_var)


def _get_gmail_accounts() -> dict[str, list[str]]:
    """Get unified_id -> gmail list mapping from DB, with .env fallback."""
    try:
        from core.config_models import UserServiceAccount

        rows = UserServiceAccount.search_sync([("service_type", "=", "gmail")])
        if rows:
            result: dict[str, list[str]] = {}
            for r in rows:
                result.setdefault(r["unified_id"], []).append(r["account_id"])
            return result
    except Exception:
        pass

    # Fallback to env (format: unified_id:email,unified_id:email)
    value = os.getenv("USER_GMAIL_ACCOUNTS", "")
    if not value:
        return {}
    accounts: dict[str, list[str]] = {}
    for item in value.split(","):
        item = item.strip()
        if ":" not in item:
            continue
        unified_id, email = item.split(":", 1)
        unified_id = unified_id.strip().lower()
        accounts.setdefault(unified_id, []).append(email.strip())
    return accounts


# Gmail accounts mapping (lazy — evaluated on first access)
# NOTE: kept as module-level for backward compat with telegram adapter import.
# Will be replaced by function calls in Phase 4.
USER_GMAIL_ACCOUNTS = _get_gmail_accounts()


def get_user_mcp_permissions(username: str, unified_id: str = None) -> list[str] | None:
    """Get MCP servers allowed for user. None = not configured (default behavior).

    Supports wildcard patterns:
    - 'gmail-*': expands to all Gmail accounts linked to the user's unified identity
    """
    try:
        from core.config_models import UserMcpPermission

        username_lower = username.lower().lstrip("@")
        rows = UserMcpPermission.search_sync([("username", "=", username_lower)])
        if not rows:
            return None

        permissions = [r["server_name"] for r in rows]

        # Expand wildcards
        uid = (unified_id or username_lower).lower()
        gmail_accounts = _get_gmail_accounts().get(uid, [])

        expanded = []
        for perm in permissions:
            if perm == "gmail-*":
                for email in gmail_accounts:
                    expanded.append(f"gmail-{email}")
            else:
                expanded.append(perm)
        return expanded
    except Exception:
        return None


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "4"))
CLAUDE_TIMEOUT_SECONDS = int(os.getenv("CLAUDE_TIMEOUT_SECONDS", "600"))
TRIGGER_WORD = os.getenv("TRIGGER_WORD", "gridbear").lower()

# Verbose logging for agent communications (prompts, responses, inter-agent)
VERBOSE_AGENT_LOG = os.getenv("VERBOSE_AGENT_LOG", "false").lower() == "true"

# Claude model: sonnet (default, faster), opus (more capable), haiku (fastest)
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "sonnet")

DATABASE_PATH = DATA_DIR / "sessions.db"


def get_unified_user_id(platform: str, username: str) -> str:
    """Get unified user ID for cross-platform memory.

    If a user_identity mapping exists, returns the unified_id.
    Otherwise returns "{platform}:{username}" as fallback.
    """
    try:
        from core.config_models import UserIdentity

        username_lower = username.lower().lstrip("@")
        platform_lower = platform.lower()
        row = UserIdentity.get_sync(platform=platform_lower, username=username_lower)
        if row:
            return row["unified_id"]
    except Exception:
        pass
    # Fallback: platform-prefixed username
    return f"{platform.lower()}:{username.lower().lstrip('@')}"


def get_memory_group_user_ids(user_id: str) -> list[str]:
    """Get all user IDs in the same memory group as the given user.

    Returns a list containing at minimum the user_id itself.
    If the user is in a memory group, returns all members of that group.
    """
    try:
        from core.config_models import MemoryGroup

        user_id_lower = user_id.lower()
        rows = MemoryGroup.search_sync()
        for r in rows:
            if r["unified_id"].lower() == user_id_lower:
                group_name = r["group_name"]
                members = MemoryGroup.search_sync([("group_name", "=", group_name)])
                return [m["unified_id"] for m in members]
    except Exception:
        pass
    return [user_id]


def get_user_memory_group_name(user_id: str) -> str | None:
    """Get the memory group name for a user."""
    try:
        from core.config_models import MemoryGroup

        user_id_lower = user_id.lower()
        rows = MemoryGroup.search_sync()
        for r in rows:
            if r["unified_id"].lower() == user_id_lower:
                return r["group_name"]
    except Exception:
        pass
    return None


def get_group_permissions(unified_id: str) -> list[str]:
    """Get MCP servers allowed for the user's groups.

    Returns combined permissions from all groups the user belongs to.
    """
    try:
        from core.config_models import GroupMcpPermission, MemoryGroup

        unified_id = unified_id.lower()
        permissions = set()

        all_groups = MemoryGroup.search_sync()
        for r in all_groups:
            if r["unified_id"].lower() == unified_id:
                group_perms = GroupMcpPermission.search_sync(
                    [("group_name", "=", r["group_name"])]
                )
                for gp in group_perms:
                    permissions.add(gp["server_name"])
        return list(permissions)
    except Exception:
        return []


def has_command_permission(unified_id: str, command: str) -> bool:
    """Check if user has permission to run a command.

    Checks group_permissions for:
    - 'command:*' (all commands)
    - 'command:<command_name>' (specific command)
    """
    permissions = get_group_permissions(unified_id)
    command_lower = command.lower().lstrip("/")

    for perm in permissions:
        if perm == "command:*":
            return True
        if perm == f"command:{command_lower}":
            return True

    return False


def get_group_gmail_accounts(unified_id: str) -> dict[str, list[str]]:
    """Get all Gmail accounts for users in the same memory groups."""
    return _get_group_accounts_for_service(unified_id, "gmail")


def _get_group_accounts_for_service(
    unified_id: str, service_type: str
) -> dict[str, list[str]]:
    """Get shared accounts for a specific service across memory groups."""
    try:
        from core.config_models import MemoryGroup, UserServiceAccount

        unified_id = unified_id.lower()

        # Find all groups this user belongs to and merge members
        group_members = {unified_id}
        all_groups = MemoryGroup.search_sync()
        for r in all_groups:
            if r["unified_id"].lower() == unified_id:
                for r2 in all_groups:
                    if r2["group_name"] == r["group_name"]:
                        group_members.add(r2["unified_id"].lower())

        # Get accounts for each group member
        result: dict[str, list[str]] = {}
        for member_id in group_members:
            rows = UserServiceAccount.search_sync(
                [
                    ("unified_id", "=", member_id),
                    ("service_type", "=", service_type),
                ]
            )
            if rows:
                result[member_id] = [r["account_id"] for r in rows]
        return result
    except Exception:
        return {}


# Plugin name -> service_type for shared accounts
_SHARED_ACCOUNT_PLUGINS = {
    "gmail": "gmail",
}


def get_group_shared_accounts(
    unified_id: str,
) -> dict[str, dict[str, list[str]]]:
    """Get all shared MCP accounts for users in the same memory groups.

    Returns: {plugin_name: {unified_id: [account_ids]}}
    """
    result = {}
    for plugin_name, service_type in _SHARED_ACCOUNT_PLUGINS.items():
        accounts = _get_group_accounts_for_service(unified_id, service_type)
        if accounts:
            result[plugin_name] = accounts
    return result


# Default locale
DEFAULT_LOCALE = "en"


def get_user_locale(unified_id: str) -> str | None:
    """Get user's preferred locale."""
    try:
        from core.config_models import UserProfile

        row = UserProfile.get_sync(unified_id=unified_id.lower())
        if row:
            return row["locale"]
    except Exception:
        pass
    return None


def set_user_locale(unified_id: str, locale: str) -> bool:
    """Set user's preferred locale."""
    try:
        from core.config_models import UserProfile

        UserProfile.create_or_update_sync(
            _conflict_fields=("unified_id",),
            _update_fields=["locale"],
            unified_id=unified_id.lower(),
            locale=locale,
        )
        return True
    except Exception:
        return False
