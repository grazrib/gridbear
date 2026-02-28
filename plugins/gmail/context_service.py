"""Context injection service for Gmail.

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


class GmailContextService(BaseService):
    """Service to inject Gmail working context."""

    name = "gmail-context"

    def __init__(self, config: dict):
        super().__init__(config)
        self.download_dir = Path(config.get("download_dir", "/app/data/attachments"))
        self.state_file = self.download_dir / "gmail_context.json"

    async def initialize(self) -> None:
        """Initialize service and register hooks."""
        logger.info("Initializing Gmail context service")

        hook_manager.register(
            "after_context_build",
            self._inject_context_hook,
            priority=8,
            plugin_name="gmail-context",
        )

        logger.info("Gmail context service initialized")

    async def shutdown(self) -> None:
        """Cleanup hooks."""
        hook_manager.unregister("after_context_build", self._inject_context_hook)
        logger.info("Gmail context service shutdown")

    async def _inject_context_hook(self, hook_data: HookData, **kwargs) -> HookData:
        """Inject working email/event context into the prompt."""
        if not hook_data.username:
            return hook_data

        context = self._get_context_for_user(hook_data.username)
        if context:
            hook_data.prompt += context
            logger.debug(f"Gmail: Injected working context for {hook_data.username}")

        return hook_data

    def _get_context_for_user(self, username: str) -> str | None:
        """Get context injection for user."""
        if not self.state_file.exists():
            return None

        try:
            with open(self.state_file, "r") as f:
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

        working_email = user_state.get("working_email")
        working_event = user_state.get("working_event")
        operations = user_state.get("operations", [])

        if not working_email and not working_event and not operations:
            return None

        # Check expiry
        now = datetime.now(timezone.utc)

        lines = ["\n\n[Gmail/Calendar - Working Context]"]

        # Working email context
        if working_email:
            try:
                email_time = datetime.fromisoformat(
                    working_email["timestamp"].replace("Z", "+00:00")
                )
                if (now - email_time).total_seconds() <= CONTEXT_EXPIRY:
                    lines.append("\n**Current Email:**")
                    lines.append(
                        f"- Subject: {working_email.get('subject', 'No subject')}"
                    )
                    lines.append(f"- From: {working_email.get('from', 'Unknown')}")
                    lines.append(f"- To: {working_email.get('to', '')}")
                    lines.append(f"- Date: {working_email.get('date', '')}")
                    lines.append(
                        f"- Message ID: `{working_email.get('message_id', '')}`"
                    )

                    if working_email.get("body_preview"):
                        preview = working_email["body_preview"]
                        if len(preview) > 500:
                            preview = preview[:500] + "..."
                        lines.append(f"\nBody preview:\n```\n{preview}\n```")
            except (KeyError, ValueError):
                pass

        # Working calendar event context
        if working_event:
            try:
                event_time = datetime.fromisoformat(
                    working_event["timestamp"].replace("Z", "+00:00")
                )
                if (now - event_time).total_seconds() <= CONTEXT_EXPIRY:
                    lines.append("\n**Current Calendar Event:**")
                    lines.append(
                        f"- Summary: {working_event.get('summary', 'No title')}"
                    )
                    lines.append(f"- Start: {working_event.get('start', '')}")
                    lines.append(f"- End: {working_event.get('end', '')}")
                    lines.append(f"- Event ID: `{working_event.get('event_id', '')}`")

                    if working_event.get("description"):
                        lines.append(
                            f"- Description: {working_event['description'][:200]}"
                        )
            except (KeyError, ValueError):
                pass

        # Recent operations
        if operations:
            lines.append("\n**Recent operations:**")
            for op in operations[:5]:
                try:
                    op_time = op.get("timestamp", "")[:16].replace("T", " ")
                    op_name = op.get("operation", "unknown")

                    if op_name == "get_email":
                        lines.append(
                            f"- [{op_time}] Read email: {op.get('subject', '')[:50]}"
                        )
                    elif op_name == "list_emails":
                        lines.append(
                            f"- [{op_time}] Listed {op.get('count', '?')} emails"
                        )
                    elif op_name == "send_email":
                        lines.append(
                            f"- [{op_time}] Sent email to {op.get('to', '')} - {op.get('subject', '')[:30]}"
                        )
                    elif op_name == "get_calendar_event":
                        lines.append(
                            f"- [{op_time}] Viewed event: {op.get('summary', '')[:50]}"
                        )
                    else:
                        lines.append(f"- [{op_time}] {op_name}")
                except Exception:
                    continue

        if len(lines) > 1:
            lines.append(
                "\nIMPORTANT: Use the message ID above when replying to or acting on this email."
            )
            return "\n".join(lines)

        return None
