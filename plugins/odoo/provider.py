import re
from pathlib import Path

from core.interfaces.mcp_provider import BaseMCPProvider
from ui.plugin_helpers import load_plugin_config
from ui.secrets_manager import secrets_manager


def _sanitize(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or "instance"


class OdooProvider(BaseMCPProvider):
    name = "odoo"

    def __init__(self, config: dict):
        super().__init__(config)
        self.server_path = Path(__file__).parent / "server.py"

    def get_server_config(self) -> dict:
        cfg = load_plugin_config("odoo") or {}
        instances = cfg.get("instances") or []
        if not isinstance(instances, list):
            return {}

        timeout = cfg.get("timeout_seconds", 30)
        allowed_models = (cfg.get("allowed_models") or "").strip()
        allow_unsafe_execute_kw = bool(cfg.get("allow_unsafe_execute_kw", False))
        allowed_methods = (cfg.get("allowed_methods") or "").strip()
        max_smart_fields = int(cfg.get("max_smart_fields", 20) or 20)
        validate_fields = bool(cfg.get("validate_fields", True))
        servers: dict[str, dict] = {}

        for inst in instances:
            if not isinstance(inst, dict):
                continue
            instance_id = (inst.get("id") or "").strip()
            url = (inst.get("url") or "").strip()
            db = (inst.get("db") or "").strip()
            username = (inst.get("username") or "").strip()
            display_name = (inst.get("name") or "").strip() or db or url
            server_name = (inst.get("server_name") or "").strip()

            if not instance_id or not url or not db or not username:
                continue

            api_key = secrets_manager.get_plain(f"odoo_api_key_{instance_id}")
            if not api_key:
                continue

            if not server_name:
                slug = _sanitize(display_name)
                server_name = f"odoo-{slug}-{instance_id}"

            servers[server_name] = {
                "command": "python",
                "args": [str(self.server_path)],
                "env": {
                    "ODOO_INSTANCE_NAME": display_name,
                    "ODOO_URL": url,
                    "ODOO_DB": db,
                    "ODOO_USERNAME": username,
                    "ODOO_API_KEY": api_key,
                    "ODOO_TIMEOUT_SECONDS": str(timeout),
                    "ODOO_ALLOWED_MODELS": allowed_models,
                    "ODOO_ALLOW_UNSAFE_EXECUTE_KW": "1"
                    if allow_unsafe_execute_kw
                    else "0",
                    "ODOO_ALLOWED_METHODS": allowed_methods,
                    "ODOO_MAX_SMART_FIELDS": str(max_smart_fields),
                    "ODOO_VALIDATE_FIELDS": "1" if validate_fields else "0",
                },
            }

        return servers

    async def health_check(self) -> bool:
        return self.server_path.exists()

    def get_server_names(self) -> list[str]:
        config = load_plugin_config("odoo") or {}
        instances = config.get("instances") or []
        if not isinstance(instances, list):
            return []
        names = []
        for inst in instances:
            if not isinstance(inst, dict):
                continue
            server_name = (inst.get("server_name") or "").strip()
            if server_name:
                names.append(server_name)
        return names

    def get_required_permissions(self) -> list[str]:
        return self.get_server_names()
