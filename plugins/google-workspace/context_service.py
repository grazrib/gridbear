"""Context injection service for Google Workspace.

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


class GoogleWorkspaceContextService(BaseService):
    """Service to inject Google Workspace working context."""

    name = "google-workspace-context"

    def __init__(self, config: dict):
        super().__init__(config)
        self.export_dir = Path(config.get("export_dir", "/app/data/exports"))
        self.state_file = self.export_dir / "gworkspace_context.json"

    async def initialize(self) -> None:
        """Initialize service and register hooks."""
        logger.info("Initializing Google Workspace context service")

        hook_manager.register(
            "after_context_build",
            self._inject_context_hook,
            priority=8,  # After base context, before other injections
            plugin_name="google-workspace-context",
        )

        logger.info("Google Workspace context service initialized")

    async def shutdown(self) -> None:
        """Cleanup hooks."""
        hook_manager.unregister("after_context_build", self._inject_context_hook)
        logger.info("Google Workspace context service shutdown")

    async def _inject_context_hook(self, hook_data: HookData, **kwargs) -> HookData:
        """Inject working document context into the prompt."""
        if not hook_data.username:
            logger.debug("GWorkspace: No username in hook_data, skipping")
            return hook_data

        context = self._get_context_for_user(hook_data.username)
        if context:
            hook_data.prompt += context
            logger.info(
                f"GWorkspace: Injected working context for {hook_data.username}"
            )
        else:
            logger.debug(f"GWorkspace: No context found for {hook_data.username}")

        return hook_data

    def _get_context_for_user(self, username: str) -> str | None:
        """Get context injection for user.

        Args:
            username: Username (will also check email-based key)

        Returns:
            Context string or None
        """
        if not self.state_file.exists():
            return None

        try:
            with open(self.state_file, "r") as f:
                state = json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

        # Try to find user state (could be username or email)
        user_state = None
        logger.debug(
            f"GWorkspace: Looking for user '{username}' in state keys: {list(state.keys())}"
        )
        for key in state:
            if username.lower() in key.lower() or key.lower() in username.lower():
                user_state = state[key]
                logger.debug(f"GWorkspace: Matched user '{username}' to key '{key}'")
                break

        if not user_state:
            logger.debug(f"GWorkspace: No match found for '{username}'")
            return None

        working_doc = user_state.get("working_document")
        operations = user_state.get("operations", [])

        if not working_doc and not operations:
            return None

        # Check if context is expired
        now = datetime.now(timezone.utc)
        if working_doc:
            try:
                doc_time = datetime.fromisoformat(
                    working_doc["timestamp"].replace("Z", "+00:00")
                )
                if (now - doc_time).total_seconds() > CONTEXT_EXPIRY:
                    return None
            except (KeyError, ValueError):
                pass

        lines = ["\n\n[Google Workspace - Working Context]"]

        if working_doc:
            doc_type_name = {
                "doc": "Google Doc",
                "sheet": "Google Sheet",
                "slide": "Google Slides",
                "drive": "Drive File",
            }.get(working_doc.get("document_type", "doc"), "Document")

            title = working_doc.get("document_title") or "Untitled"
            lines.append(f"You are currently working on: **{title}** ({doc_type_name})")
            lines.append(f"Document ID: `{working_doc.get('document_id', 'unknown')}`")

            if working_doc.get("content_summary"):
                summary = working_doc["content_summary"]
                if len(summary) > 500:
                    summary = summary[:500] + "..."
                lines.append(f"\nContent preview:\n```\n{summary}\n```")

        if operations:
            lines.append("\nRecent operations:")
            for op in operations[:5]:
                try:
                    op_time = op.get("timestamp", "")[:16].replace("T", " ")
                    title = op.get("document_title") or op.get("document_id", "")[:20]
                    tool = op.get("tool_name", op.get("operation", "unknown"))
                    lines.append(f"- [{op_time}] {tool}: {title}")
                except Exception:
                    continue

        lines.append(
            "\nIMPORTANT: Use the document ID above when working with this document."
        )

        return "\n".join(lines)
