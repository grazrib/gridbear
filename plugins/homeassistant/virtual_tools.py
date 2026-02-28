"""Home Assistant Camera Virtual Tool Provider.

Exposes camera snapshot tools as virtual MCP tools,
using HA REST API directly (no separate MCP server needed).
"""

import base64
import json
from datetime import datetime
from pathlib import Path

import httpx

from config.logging_config import logger
from core.interfaces.local_tools import LocalToolProvider

_SERVER_NAME = "ha_camera"
_OUTPUT_DIR = Path("/app/data/attachments")

_TOOLS = [
    {
        "name": "ha_camera__get_camera_snapshot",
        "description": (
            "Capture a snapshot from a Home Assistant camera. "
            "Saves the image and returns both the file path and base64 data."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "camera_entity_id": {
                    "type": "string",
                    "description": "Camera entity ID (e.g., camera.front_door)",
                }
            },
            "required": ["camera_entity_id"],
        },
    },
    {
        "name": "ha_camera__list_cameras",
        "description": "List all available camera entities in Home Assistant.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _get_ha_config() -> tuple[str, str]:
    """Read HA URL and token from plugin config + secrets."""
    from ui.secrets_manager import secrets_manager

    ha_url = "http://homeassistant.local:8123"
    try:
        from core.plugin_registry.models import PluginRegistryEntry

        entry = PluginRegistryEntry.get_sync(name="homeassistant")
        if entry:
            config = entry.get("config") or {}
            ha_url = config.get("ha_url", ha_url)
    except Exception:
        pass

    token = secrets_manager.get_plain("HA_TOKEN") or ""
    return ha_url.rstrip("/"), token


class HomeAssistantCameraToolProvider(LocalToolProvider):
    """Exposes HA camera tools as virtual MCP tools."""

    def get_server_name(self) -> str:
        return _SERVER_NAME

    def get_tools(self) -> list[dict]:
        return _TOOLS

    async def handle_tool_call(
        self, tool_name: str, arguments: dict, **kwargs
    ) -> list[dict]:
        action = tool_name.replace("ha_camera__", "")
        logger.info("ha_camera tool: %s", action)

        ha_url, token = _get_ha_config()
        if not token:
            return [{"type": "text", "text": "Error: HA_TOKEN not configured"}]

        if action == "get_camera_snapshot":
            return await self._snapshot(ha_url, token, arguments)
        elif action == "list_cameras":
            return await self._list(ha_url, token)
        return [{"type": "text", "text": f"Unknown action: {action}"}]

    async def _snapshot(self, ha_url: str, token: str, arguments: dict) -> list[dict]:
        """Capture a snapshot from a HA camera."""
        camera_entity_id = arguments.get("camera_entity_id", "")
        if not camera_entity_id:
            return [{"type": "text", "text": "Error: camera_entity_id is required"}]

        if not camera_entity_id.startswith("camera."):
            camera_entity_id = f"camera.{camera_entity_id}"

        url = f"{ha_url}/api/camera_proxy/{camera_entity_id}"
        headers = {"Authorization": f"Bearer {token}"}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, headers=headers)

                if response.status_code == 404:
                    cameras_result = await self._list_cameras_raw(ha_url, token, client)
                    available = [
                        c["entity_id"] for c in cameras_result.get("cameras", [])
                    ]
                    return [
                        {
                            "type": "text",
                            "text": (
                                f"Camera '{camera_entity_id}' not found. "
                                f"Available cameras: {', '.join(available)}"
                            ),
                        }
                    ]

                response.raise_for_status()
                image_data = response.content

        except httpx.HTTPStatusError as e:
            return [{"type": "text", "text": f"HTTP error: {e}"}]
        except Exception as e:
            return [{"type": "text", "text": f"Error fetching snapshot: {e}"}]

        # Save image to file
        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        camera_name = camera_entity_id.replace("camera.", "").replace(".", "_")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{camera_name}_{timestamp}.jpg"
        filepath = _OUTPUT_DIR / filename

        with open(filepath, "wb") as f:
            f.write(image_data)

        base64_image = base64.b64encode(image_data).decode("utf-8")

        return [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "camera": camera_entity_id,
                        "file_path": str(filepath),
                        "size_bytes": len(image_data),
                        "message": (
                            f"Snapshot saved to {filepath}. "
                            "You can send this file to the user "
                            "or analyze it with vision."
                        ),
                    },
                    indent=2,
                ),
            },
            {
                "type": "image",
                "data": base64_image,
                "mimeType": "image/jpeg",
            },
        ]

    async def _list(self, ha_url: str, token: str) -> list[dict]:
        """List all camera entities."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                result = await self._list_cameras_raw(ha_url, token, client)
        except Exception as e:
            return [{"type": "text", "text": f"Error listing cameras: {e}"}]

        return [{"type": "text", "text": json.dumps(result, indent=2)}]

    @staticmethod
    async def _list_cameras_raw(
        ha_url: str, token: str, client: httpx.AsyncClient
    ) -> dict:
        """Fetch camera list from HA API (reusable by snapshot 404 handler)."""
        url = f"{ha_url}/api/states"
        headers = {"Authorization": f"Bearer {token}"}
        response = await client.get(url, headers=headers)
        response.raise_for_status()

        states = response.json()
        cameras = [
            {
                "entity_id": e["entity_id"],
                "friendly_name": e.get("attributes", {}).get(
                    "friendly_name", e["entity_id"]
                ),
                "state": e["state"],
            }
            for e in states
            if e["entity_id"].startswith("camera.")
        ]
        return {"cameras": cameras, "count": len(cameras)}
