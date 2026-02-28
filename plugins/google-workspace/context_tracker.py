"""Context tracker for Google Workspace operations.

Tracks recent document operations to maintain context across conversation turns.
Uses a shared state file that the MCP server writes to and the service reads from.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from config.logging_config import logger

# Shared state file location
STATE_DIR = Path(os.environ.get("GRIDBEAR_DATA_DIR", "/app/data"))
STATE_FILE = STATE_DIR / "gworkspace_context.json"

# Maximum operations to track per user
MAX_OPERATIONS = 10

# Context expiry in seconds (30 minutes)
CONTEXT_EXPIRY = 1800


def _load_state() -> dict:
    """Load state from file."""
    if not STATE_FILE.exists():
        return {}
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save_state(state: dict) -> None:
    """Save state to file."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except IOError as e:
        logger.error(f"Failed to save workspace context: {e}")


def record_operation(
    user_id: str,
    operation: str,
    document_id: str,
    document_title: str = "",
    document_type: str = "doc",
    content_summary: str = "",
    extra_data: dict | None = None,
) -> None:
    """Record a Google Workspace operation.

    Args:
        user_id: Unified user ID
        operation: Operation type (read, create, update, etc.)
        document_id: Google document ID
        document_title: Document title
        document_type: Type (doc, sheet, slide)
        content_summary: Brief summary of content (first 500 chars)
        extra_data: Additional context data
    """
    state = _load_state()

    if user_id not in state:
        state[user_id] = {"operations": [], "working_document": None}

    timestamp = datetime.now(timezone.utc).isoformat()

    op_record = {
        "timestamp": timestamp,
        "operation": operation,
        "document_id": document_id,
        "document_title": document_title,
        "document_type": document_type,
        "content_summary": content_summary[:500] if content_summary else "",
    }

    if extra_data:
        op_record["extra"] = extra_data

    # Add to operations list
    state[user_id]["operations"].insert(0, op_record)
    state[user_id]["operations"] = state[user_id]["operations"][:MAX_OPERATIONS]

    # Update working document if this was a read/create operation
    if operation in ("read", "create", "open"):
        state[user_id]["working_document"] = {
            "document_id": document_id,
            "document_title": document_title,
            "document_type": document_type,
            "content_summary": content_summary[:1000] if content_summary else "",
            "timestamp": timestamp,
        }

    _save_state(state)
    logger.debug(
        f"Recorded workspace operation: {operation} on {document_title or document_id}"
    )


def get_user_context(user_id: str) -> str | None:
    """Get context injection for user.

    Args:
        user_id: Unified user ID

    Returns:
        Context string to inject or None
    """
    state = _load_state()

    if user_id not in state:
        return None

    user_state = state[user_id]
    working_doc = user_state.get("working_document")
    operations = user_state.get("operations", [])

    if not working_doc and not operations:
        return None

    # Check if context is expired
    now = datetime.now(timezone.utc)
    if working_doc:
        doc_time = datetime.fromisoformat(
            working_doc["timestamp"].replace("Z", "+00:00")
        )
        if (now - doc_time).total_seconds() > CONTEXT_EXPIRY:
            # Context expired, clear it
            clear_user_context(user_id)
            return None

    lines = ["\n[Google Workspace - Working Context]"]

    if working_doc:
        doc_type_name = {
            "doc": "Google Doc",
            "sheet": "Google Sheet",
            "slide": "Google Slides",
        }.get(working_doc["document_type"], "Document")

        lines.append(
            f"You are currently working on: **{working_doc['document_title'] or 'Untitled'}** ({doc_type_name})"
        )
        lines.append(f"Document ID: `{working_doc['document_id']}`")

        if working_doc.get("content_summary"):
            # Truncate and format content summary
            summary = working_doc["content_summary"]
            if len(summary) > 500:
                summary = summary[:500] + "..."
            lines.append(f"\nContent preview:\n```\n{summary}\n```")

    if operations:
        lines.append("\nRecent operations:")
        for op in operations[:5]:
            op_time = op["timestamp"][:16].replace("T", " ")
            title = op.get("document_title") or op["document_id"][:20]
            lines.append(f"- [{op_time}] {op['operation']}: {title}")

    return "\n".join(lines)


def clear_user_context(user_id: str) -> None:
    """Clear context for a user.

    Args:
        user_id: Unified user ID
    """
    state = _load_state()
    if user_id in state:
        del state[user_id]
        _save_state(state)


def get_working_document(user_id: str) -> dict | None:
    """Get the current working document for a user.

    Args:
        user_id: Unified user ID

    Returns:
        Working document info or None
    """
    state = _load_state()
    if user_id not in state:
        return None
    return state[user_id].get("working_document")
