from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ui.auth.database import auth_db
from ui.config_manager import ConfigManager
from ui.jinja_env import templates
from ui.routes.auth import require_login
from ui.utils.channels import get_available_channels

router = APIRouter()
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ADMIN_DIR = Path(__file__).resolve().parent.parent


def get_enabled_plugins_by_type() -> dict:
    """Get enabled plugins grouped by type."""
    from ui.app import get_enabled_plugins_by_type as _get

    return _get()


def get_template_context(request: Request, **kwargs) -> dict:
    """Get base template context with enabled plugins and menus."""
    plugins = get_enabled_plugins_by_type()
    plugin_menus = getattr(request.state, "plugin_menus", [])
    return {
        "request": request,
        "enabled_channels": plugins.get("channels", []),
        "enabled_services": plugins.get("services", []),
        "enabled_mcp": plugins.get("mcp", []),
        "enabled_runners": plugins.get("runners", []),
        "plugin_menus": plugin_menus,
        **kwargs,
    }


def _get_valid_channel_names() -> set[str]:
    """Get set of valid channel names for route validation."""
    return {ch["name"] for ch in get_available_channels()}


@router.get("/", response_class=HTMLResponse)
async def users_page(request: Request, _: bool = Depends(require_login)):
    config = ConfigManager()
    portal_users = auth_db.get_all_users()

    # Build channels list with their users
    channels = get_available_channels()
    for ch in channels:
        ch["users"] = config.get_channel_users(ch["name"])

    return templates.TemplateResponse(
        "users.html",
        get_template_context(
            request,
            channels=channels,
            user_identities=config.get_user_identities(),
            user_locales=config.get_user_locales(),
            available_locales=config.get_available_locales(),
            portal_users=portal_users,
            all_unified_ids=config.get_all_unified_ids(),
        ),
    )


# User identities (cross-platform linking)
@router.post("/identity/add")
async def add_user_identity(
    request: Request,
    unified_id: str = Form(...),
    locale: str = Form(default="en"),
    _: bool = Depends(require_login),
):
    config = ConfigManager()
    unified_id = unified_id.strip().lower()
    if unified_id:
        # Read platform usernames dynamically from form data
        form_data = await request.form()
        for ch_name in _get_valid_channel_names():
            value = form_data.get(ch_name, "").strip()
            if value:
                config.add_user_identity(unified_id, ch_name, value)
        if locale.strip():
            config.set_user_locale(unified_id, locale.strip())
    return RedirectResponse(url="/users", status_code=303)


@router.post("/identity/{unified_id}/set-locale")
async def set_user_locale(
    request: Request,
    unified_id: str,
    locale: str = Form(...),
    _: bool = Depends(require_login),
):
    config = ConfigManager()
    config.set_user_locale(unified_id, locale)
    return RedirectResponse(url="/users", status_code=303)


@router.post("/identity/{unified_id}/remove-platform")
async def remove_identity_platform(
    request: Request,
    unified_id: str,
    platform: str = Form(...),
    _: bool = Depends(require_login),
):
    config = ConfigManager()
    config.remove_user_identity(unified_id, platform)
    return RedirectResponse(url="/users", status_code=303)


@router.post("/identity/{unified_id}/delete")
async def delete_user_identity(
    request: Request,
    unified_id: str,
    _: bool = Depends(require_login),
):
    config = ConfigManager()
    config.remove_user_identity(unified_id)
    return RedirectResponse(url="/users", status_code=303)


# --- Portal Users (admin_auth.db) ---

MIN_PASSWORD_LENGTH = 8


@router.post("/portal/create")
async def create_portal_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    unified_id: str = Form(default=""),
    display_name: str = Form(default=""),
    is_superadmin: str = Form(default=""),
    _: bool = Depends(require_login),
):
    """Create a new portal user."""
    from ui.routes.auth import hash_password

    username = username.strip().lower()
    if not username or len(password) < MIN_PASSWORD_LENGTH:
        return RedirectResponse(url="/users?error=invalid_input", status_code=303)

    # Check if username already exists
    existing = auth_db.get_user_by_username(username)
    if existing:
        return RedirectResponse(url="/users?error=username_exists", status_code=303)

    auth_db.create_user(
        username=username,
        password_hash=hash_password(password),
        unified_id=unified_id.strip() or None,
        display_name=display_name.strip() or None,
        is_superadmin=is_superadmin == "1",
    )

    return RedirectResponse(url="/users", status_code=303)


@router.post("/portal/{user_id}/update")
async def update_portal_user(
    request: Request,
    user_id: int,
    unified_id: str = Form(default=""),
    display_name: str = Form(default=""),
    is_superadmin: str = Form(default=""),
    is_active: str = Form(default=""),
    _: bool = Depends(require_login),
):
    """Update a portal user."""
    auth_db.update_user(
        user_id,
        unified_id=unified_id.strip() or None,
        display_name=display_name.strip() or None,
        is_superadmin=1 if is_superadmin == "1" else 0,
        is_active=1 if is_active == "1" else 0,
    )
    return RedirectResponse(url="/users", status_code=303)


@router.post("/portal/{user_id}/reset-password")
async def reset_portal_user_password(
    request: Request,
    user_id: int,
    new_password: str = Form(...),
    _: bool = Depends(require_login),
):
    """Reset a portal user's password."""
    from ui.routes.auth import hash_password

    if len(new_password) < MIN_PASSWORD_LENGTH:
        return RedirectResponse(url="/users?error=password_short", status_code=303)

    auth_db.update_user(user_id, password_hash=hash_password(new_password))
    return RedirectResponse(url="/users", status_code=303)


@router.post("/portal/{user_id}/delete")
async def delete_portal_user(
    request: Request,
    user_id: int,
    admin_user: dict = Depends(require_login),
):
    """Delete a portal user."""
    # Prevent self-deletion
    if user_id == admin_user.get("id"):
        return RedirectResponse(url="/users?error=self_delete", status_code=303)

    auth_db.delete_user(user_id)
    return RedirectResponse(url="/users", status_code=303)


# --- Generic platform routes (MUST be last to avoid matching /identity/*, /portal/*) ---


@router.post("/{platform}/add")
async def add_channel_user(
    request: Request,
    platform: str,
    user_id: str = Form(default=""),
    username: str = Form(default=""),
    _: bool = Depends(require_login),
):
    if platform not in _get_valid_channel_names():
        return RedirectResponse(url="/users", status_code=303)
    config = ConfigManager()
    uid = int(user_id) if user_id.strip().isdigit() else None
    uname = username.strip() if username.strip() else None
    if uid or uname:
        config.add_channel_user(platform, user_id=uid, username=uname)
    return RedirectResponse(url="/users", status_code=303)


@router.post("/{platform}/remove")
async def remove_channel_user(
    request: Request,
    platform: str,
    user_id: str = Form(default=""),
    username: str = Form(default=""),
    _: bool = Depends(require_login),
):
    if platform not in _get_valid_channel_names():
        return RedirectResponse(url="/users", status_code=303)
    config = ConfigManager()
    uid = int(user_id) if user_id.strip().isdigit() else None
    uname = username.strip() if username.strip() else None
    if uid or uname:
        config.remove_channel_user(platform, user_id=uid, username=uname)
    return RedirectResponse(url="/users", status_code=303)
