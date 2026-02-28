from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ui.config_manager import ConfigManager
from ui.jinja_env import templates
from ui.routes.auth import require_login

router = APIRouter()
ADMIN_DIR = Path(__file__).resolve().parent.parent


@router.get("/", response_class=HTMLResponse)
async def permissions_page(request: Request, _: bool = Depends(require_login)):
    from ui.utils.channels import get_available_channels, get_channel_ui_map

    config = ConfigManager()
    permissions = config.get_all_user_permissions()
    available_servers = config.get_available_mcp_servers()

    # Fallback: collect server names from existing permissions when
    # plugin_manager is unavailable (admin runs in a separate container)
    if not available_servers:
        seen = set()
        for servers in permissions.values():
            seen.update(servers)
        for servers in config.get_all_group_permissions().values():
            seen.update(servers)
        available_servers = sorted(seen)

    # Get platform info dynamically for all available channels
    channels = get_available_channels()
    channel_users = {}
    for ch in channels:
        channel_users[ch["name"]] = set(
            u.lower() for u in config.get_channel_users(ch["name"]).get("usernames", [])
        )

    # Get unified identities
    identities = config.get_user_identities()

    # Build set of usernames that are linked to identities (to exclude them)
    linked_usernames = set()
    for identity_data in identities.values():
        for channel_username in identity_data.values():
            linked_usernames.add(channel_username.lower())

    # Include all authorized users, even without permissions yet
    # But exclude platform usernames that are already linked to an identity
    all_users = set()
    all_users.update(identities.keys())  # Add unified identities

    # Add users from permissions only if not linked to an identity
    for u in permissions.keys():
        if u.lower() not in linked_usernames:
            all_users.add(u)

    # Add platform users only if not linked to an identity
    for ch_name, ch_users in channel_users.items():
        for u in ch_users:
            if u not in linked_usernames:
                all_users.add(u)

    # Build filtered permissions dict
    filtered_permissions = {}
    for user in all_users:
        # For identities, merge permissions from all linked usernames
        if user in identities:
            merged = set(permissions.get(user, []))
            for channel_username in identities[user].values():
                merged.update(permissions.get(channel_username, []))
            filtered_permissions[user] = list(merged)
        else:
            filtered_permissions[user] = permissions.get(user, [])

    permissions = filtered_permissions

    user_platforms = {}
    for username in permissions.keys():
        platforms = []
        username_lower = username.lower()
        # Check direct platform authorization
        for ch_name, ch_users in channel_users.items():
            if username_lower in ch_users:
                platforms.append(ch_name)
        # Check via identity mapping
        if username in identities:
            identity = identities[username]
            for ch_name in channel_users:
                if identity.get(ch_name):
                    platforms.append(ch_name)
        user_platforms[username] = list(set(platforms))  # Remove duplicates

    # Get group permissions
    memory_groups = config.get_memory_groups()
    group_permissions = config.get_all_group_permissions()

    plugin_menus = getattr(request.state, "plugin_menus", [])
    return templates.TemplateResponse(
        "permissions.html",
        {
            "request": request,
            "plugin_menus": plugin_menus,
            "permissions": permissions,
            "available_servers": available_servers,
            "user_platforms": user_platforms,
            "channel_ui": get_channel_ui_map(),
            "memory_groups": memory_groups,
            "group_permissions": group_permissions,
        },
    )


@router.post("/save")
async def save_permissions(
    request: Request,
    username: str = Form(...),
    servers: List[str] = Form(default=[]),
    _: bool = Depends(require_login),
):
    config = ConfigManager()
    config.set_user_permissions(username, servers)
    return RedirectResponse(url="/permissions/", status_code=303)


@router.post("/delete/{username}")
async def delete_permissions(
    request: Request,
    username: str,
    _: bool = Depends(require_login),
):
    config = ConfigManager()
    config.delete_user_permissions(username)
    return RedirectResponse(url="/permissions/", status_code=303)


@router.post("/group/save")
async def save_group_permissions(
    request: Request,
    group_name: str = Form(...),
    servers: List[str] = Form(default=[]),
    _: bool = Depends(require_login),
):
    config = ConfigManager()
    existing_groups = config.get_memory_groups()
    if group_name not in existing_groups:
        config.add_memory_group(group_name, members=[])
    config.set_group_permissions(group_name, servers)
    return RedirectResponse(url="/permissions/", status_code=303)


@router.post("/group/delete/{group_name}")
async def delete_group(
    request: Request,
    group_name: str,
    _: bool = Depends(require_login),
):
    config = ConfigManager()
    config.delete_group_permissions(group_name)
    config.delete_memory_group(group_name)
    return RedirectResponse(url="/permissions/", status_code=303)


@router.post("/group/{group_name}/remove-member")
async def remove_group_member(
    request: Request,
    group_name: str,
    unified_id: str = Form(...),
    _: bool = Depends(require_login),
):
    config = ConfigManager()
    config.remove_user_from_memory_group(group_name, unified_id)
    return RedirectResponse(url="/permissions/", status_code=303)
