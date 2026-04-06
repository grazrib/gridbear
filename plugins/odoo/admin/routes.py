import re
import secrets

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ui.csrf import validate_csrf_token
from ui.jinja_env import templates
from ui.plugin_helpers import (
    load_plugin_config,
    save_plugin_config,
)
from ui.routes.auth import require_login
from ui.routes.plugins import get_plugin_info, get_template_context
from ui.secrets_manager import secrets_manager

router = APIRouter(prefix="/plugins/odoo", tags=["odoo"])


def _sanitize(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or "odoo"


def _get_config() -> dict:
    cfg = load_plugin_config("odoo") or {}
    if not isinstance(cfg, dict):
        return {}
    instances = cfg.get("instances")
    if instances is None:
        cfg["instances"] = []
    elif not isinstance(instances, list):
        cfg["instances"] = []
    return cfg


def _save_and_refresh(cfg: dict) -> None:
    save_plugin_config("odoo", cfg)
    try:
        from core.mcp_gateway.server import get_client_manager

        cm = get_client_manager()
        if cm:
            import asyncio

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(cm.refresh_providers())
            except RuntimeError:
                asyncio.run(cm.refresh_providers())
    except Exception:
        pass


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def odoo_instances_page(request: Request, _=Depends(require_login)):
    cfg = _get_config()
    instances = cfg.get("instances") or []

    rows = []
    for inst in instances:
        if not isinstance(inst, dict):
            continue
        instance_id = (inst.get("id") or "").strip()
        secret_key = f"odoo_api_key_{instance_id}" if instance_id else ""
        has_secret = bool(
            secret_key and secrets_manager.get_plain(secret_key, default="")
        )
        rows.append(
            {
                "id": instance_id,
                "name": inst.get("name") or "",
                "server_name": inst.get("server_name") or "",
                "url": inst.get("url") or "",
                "db": inst.get("db") or "",
                "username": inst.get("username") or "",
                "has_secret": has_secret,
            }
        )

    plugin_info = get_plugin_info("odoo")
    return templates.TemplateResponse(
        "odoo.html",
        get_template_context(
            request,
            plugin=plugin_info,
            plugin_name="odoo",
            instances=rows,
            timeout_seconds=cfg.get("timeout_seconds", 30),
            allowed_models=cfg.get("allowed_models", ""),
            allow_unsafe_execute_kw=bool(cfg.get("allow_unsafe_execute_kw", False)),
            allowed_methods=cfg.get("allowed_methods", ""),
            max_smart_fields=cfg.get("max_smart_fields", 20),
            validate_fields=bool(cfg.get("validate_fields", True)),
        ),
    )


@router.post("/add")
async def add_instance(
    request: Request,
    name: str = Form(...),
    url: str = Form(...),
    db: str = Form(...),
    username: str = Form(...),
    api_key: str = Form(...),
    csrf_token: str = Form(...),
    _=Depends(require_login),
):
    validate_csrf_token(request, csrf_token)
    cfg = _get_config()
    instances = cfg.get("instances") or []

    instance_id = secrets.token_hex(4)
    slug = _sanitize(name or db or url)
    server_name = f"odoo-{slug}-{instance_id}"

    secrets_manager.set(
        f"odoo_api_key_{instance_id}",
        api_key.strip(),
        description=f"Odoo API key for {name.strip()}",
    )

    instances.append(
        {
            "id": instance_id,
            "name": name.strip(),
            "server_name": server_name,
            "url": url.strip().rstrip("/"),
            "db": db.strip(),
            "username": username.strip(),
        }
    )
    cfg["instances"] = instances

    _save_and_refresh(cfg)
    return RedirectResponse(url="/plugins/odoo?added=1", status_code=303)


@router.post("/remove/{instance_id}")
async def remove_instance(
    request: Request,
    instance_id: str,
    csrf_token: str = Form(...),
    _=Depends(require_login),
):
    validate_csrf_token(request, csrf_token)
    cfg = _get_config()
    instances = cfg.get("instances") or []
    kept = []
    for inst in instances:
        if isinstance(inst, dict) and (inst.get("id") or "").strip() == instance_id:
            continue
        kept.append(inst)
    cfg["instances"] = kept
    try:
        secrets_manager.delete(f"odoo_api_key_{instance_id}")
    except Exception:
        pass
    _save_and_refresh(cfg)
    return RedirectResponse(url="/plugins/odoo?removed=1", status_code=303)


@router.post("/settings")
async def save_settings(
    request: Request,
    timeout_seconds: int = Form(30),
    allowed_models: str = Form(""),
    allow_unsafe_execute_kw: str = Form(""),
    allowed_methods: str = Form(""),
    max_smart_fields: int = Form(20),
    validate_fields: str = Form(""),
    csrf_token: str = Form(...),
    _=Depends(require_login),
):
    validate_csrf_token(request, csrf_token)
    cfg = _get_config()
    cfg["timeout_seconds"] = int(timeout_seconds or 30)
    cfg["allowed_models"] = allowed_models.strip()
    cfg["allow_unsafe_execute_kw"] = allow_unsafe_execute_kw in ("on", "true", "1")
    cfg["allowed_methods"] = allowed_methods.strip()
    cfg["max_smart_fields"] = int(max_smart_fields or 20)
    cfg["validate_fields"] = validate_fields in ("on", "true", "1")
    _save_and_refresh(cfg)
    return RedirectResponse(url="/plugins/odoo?saved=1", status_code=303)
