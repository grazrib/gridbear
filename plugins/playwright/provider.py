"""Playwright MCP Provider Plugin.

Provides Playwright browser automation via MCP server.
"""

import asyncio
import time
from pathlib import Path

from config.logging_config import logger
from core.hooks import hook
from core.interfaces.mcp_provider import BaseMCPProvider


class PlaywrightProvider(BaseMCPProvider):
    """Playwright MCP server provider."""

    name = "playwright"

    def __init__(self, config: dict):
        super().__init__(config)
        self.headless = config.get("headless", True)

    async def initialize(self) -> None:
        """Initialize provider."""
        output_dir = Path(self.config.get("output_dir", "/app/data/playwright"))
        output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            f"Playwright MCP provider initialized (headless={self.headless}, "
            f"output_dir={output_dir})"
        )

    async def shutdown(self) -> None:
        """Cleanup resources."""
        pass

    def get_server_config(self) -> dict:
        """Get MCP server configuration."""
        args = ["--no-sandbox"]  # Required for Docker/root execution
        if self.headless:
            args.append("--headless")

        output_dir = self.config.get("output_dir", "/app/data/playwright")
        args.extend(["--output-dir", output_dir])

        return {
            "command": "playwright-mcp",
            "args": args,
            "cwd": output_dir,
        }

    async def health_check(self) -> bool:
        """Check if MCP server is available."""
        # The server starts on demand, so we just check if npx is available
        import shutil

        return shutil.which("npx") is not None

    def get_required_permissions(self) -> list[str]:
        """Permissions required to use this provider."""
        return ["playwright"]

    def get_allowed_tools(self) -> list[str]:
        """Tools to allow in Claude CLI (for command-based MCP servers)."""
        return [
            "mcp__playwright__browser_navigate",
            "mcp__playwright__browser_navigate_back",
            "mcp__playwright__browser_tabs",
            "mcp__playwright__browser_click",
            "mcp__playwright__browser_type",
            "mcp__playwright__browser_hover",
            "mcp__playwright__browser_select_option",
            "mcp__playwright__browser_press_key",
            "mcp__playwright__browser_drag",
            "mcp__playwright__browser_snapshot",
            "mcp__playwright__browser_take_screenshot",
            "mcp__playwright__browser_fill_form",
            "mcp__playwright__browser_file_upload",
            "mcp__playwright__browser_wait_for",
            "mcp__playwright__browser_console_messages",
            "mcp__playwright__browser_network_requests",
            "mcp__playwright__browser_evaluate",
            "mcp__playwright__browser_install",
            "mcp__playwright__browser_close",
            "mcp__playwright__browser_resize",
            "mcp__playwright__browser_handle_dialog",
            "mcp__playwright__browser_run_code",
        ]


@hook("on_startup", priority=90)
async def _start_screenshot_cleanup(data, **kwargs):
    """Start periodic cleanup of old Playwright screenshots."""

    async def _cleanup_loop():
        cleanup_dir = Path("/app/data/playwright")
        max_age_seconds = 3600

        while True:
            await asyncio.sleep(900)
            try:
                if not cleanup_dir.exists():
                    continue
                now = time.time()
                count = 0
                for f in cleanup_dir.iterdir():
                    if f.is_file() and (now - f.stat().st_mtime) > max_age_seconds:
                        f.unlink()
                        count += 1
                if count:
                    logger.info(f"Playwright cleanup: removed {count} old files")
            except Exception as e:
                logger.warning(f"Playwright cleanup error: {e}")

    asyncio.create_task(_cleanup_loop())
    return data
