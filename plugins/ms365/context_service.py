"""Context injection service for MS365.

Reads tracked operations from the MCP server and injects
relevant context into the conversation.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from config.logging_config import logger
from core.hooks import HookData, hook_manager
from core.interfaces.service import BaseService

# Context expiry in seconds (30 minutes)
CONTEXT_EXPIRY = 1800

# State file path
STATE_DIR = Path("/app/data")
STATE_FILE = STATE_DIR / "ms365_context.json"


class MS365ContextService(BaseService):
    """Service to inject MS365 working context."""

    name = "ms365-context"

    def __init__(self, config: dict):
        super().__init__(config)

    async def initialize(self) -> None:
        """Initialize service and register hooks."""
        logger.info("Initializing MS365 context service")

        hook_manager.register(
            "after_context_build",
            self._inject_context_hook,
            priority=8,
            plugin_name="ms365-context",
        )

        logger.info("MS365 context service initialized")

    async def shutdown(self) -> None:
        """Cleanup hooks."""
        hook_manager.unregister("after_context_build", self._inject_context_hook)
        logger.info("MS365 context service shutdown")

    async def _inject_context_hook(self, hook_data: HookData, **kwargs) -> HookData:
        """Inject working MS365 context into the prompt."""
        if not hook_data.username:
            return hook_data

        context = self._get_context_for_user(hook_data.username)
        if context:
            hook_data.prompt += context
            logger.debug(f"MS365: Injected working context for {hook_data.username}")

        return hook_data

    def _get_context_for_user(self, username: str) -> str | None:
        """Get context injection for user."""
        if not STATE_FILE.exists():
            return None

        try:
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

        # Try to find user state
        user_state = None
        for key in state:
            if username.lower() in key.lower() or key.lower() in username.lower():
                user_state = state[key]
                break

        if not user_state:
            return None

        working_file = user_state.get("working_file")
        working_task = user_state.get("working_task")
        operations = user_state.get("operations", [])

        if not working_file and not working_task and not operations:
            return None

        # Check expiry
        now = datetime.now(timezone.utc)

        lines = ["\n\n[Microsoft 365 - Working Context]"]

        # Working file context
        if working_file:
            try:
                file_time = datetime.fromisoformat(
                    working_file["timestamp"].replace("Z", "+00:00")
                )
                if (now - file_time).total_seconds() <= CONTEXT_EXPIRY:
                    lines.append(
                        f"\n**Current File ({working_file.get('tenant', '')}):**"
                    )
                    lines.append(f"- Name: {working_file.get('name', '')}")
                    lines.append(f"- Path: {working_file.get('path', '')}")
                    lines.append(f"- Site: {working_file.get('site_name', '')}")
                    if working_file.get("site_id"):
                        lines.append(f"- Site ID: `{working_file['site_id']}`")
            except (KeyError, ValueError):
                pass

        # Working Planner task context
        if working_task:
            try:
                task_time = datetime.fromisoformat(
                    working_task["timestamp"].replace("Z", "+00:00")
                )
                if (now - task_time).total_seconds() <= CONTEXT_EXPIRY:
                    lines.append(
                        f"\n**Current Planner Task ({working_task.get('tenant', '')}):**"
                    )
                    lines.append(f"- Title: {working_task.get('title', '')}")
                    lines.append(f"- Plan: {working_task.get('plan_name', '')}")
                    lines.append(
                        f"- Status: {working_task.get('percent_complete', 0)}% complete"
                    )
                    if working_task.get("task_id"):
                        lines.append(f"- Task ID: `{working_task['task_id']}`")
            except (KeyError, ValueError):
                pass

        # Recent operations
        if operations:
            lines.append("\n**Recent MS365 operations:**")
            for op in operations[:5]:
                try:
                    op_time = op.get("timestamp", "")[:16].replace("T", " ")
                    op_name = op.get("operation", "unknown")
                    tenant = op.get("tenant", "")

                    if op_name == "list_sites":
                        lines.append(
                            f"- [{op_time}] Listed {op.get('count', '?')} SharePoint sites ({tenant})"
                        )
                    elif op_name == "list_files":
                        lines.append(
                            f"- [{op_time}] Listed files in {op.get('path', '/')} ({tenant})"
                        )
                    elif op_name == "read_file":
                        lines.append(
                            f"- [{op_time}] Read: {op.get('file_name', '')} ({tenant})"
                        )
                    elif op_name == "write_file":
                        lines.append(
                            f"- [{op_time}] Wrote: {op.get('file_name', '')} ({tenant})"
                        )
                    elif op_name == "list_tasks":
                        lines.append(
                            f"- [{op_time}] Listed {op.get('count', '?')} tasks ({tenant})"
                        )
                    elif op_name == "create_task":
                        lines.append(
                            f"- [{op_time}] Created task: {op.get('title', '')} ({tenant})"
                        )
                    elif op_name == "complete_task":
                        lines.append(f"- [{op_time}] Completed task ({tenant})")
                    else:
                        lines.append(f"- [{op_time}] {op_name} ({tenant})")
                except Exception:
                    continue

        if len(lines) > 1:
            lines.append("\nUse the IDs above when working with these MS365 resources.")
            return "\n".join(lines)

        return None
