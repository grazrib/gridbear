import json
from dataclasses import dataclass

from config.logging_config import logger


@dataclass
class ClaudeResponse:
    text: str
    session_id: str | None
    cost_usd: float
    is_error: bool
    raw: dict
    error_type: str | None = None


def parse_claude_output(output: str) -> ClaudeResponse:
    """Parse JSON output from Claude Code CLI."""
    try:
        data = json.loads(output)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Claude output: {e}")
        return ClaudeResponse(
            text=output,
            session_id=None,
            cost_usd=0.0,
            is_error=True,
            raw={},
        )

    result_text = ""
    if "result" in data:
        result_text = data["result"]
    elif "messages" in data:
        for msg in data.get("messages", []):
            if msg.get("type") == "assistant":
                for content in msg.get("content", []):
                    if content.get("type") == "text":
                        result_text += content.get("text", "")

    session_id = data.get("session_id")
    cost_usd = data.get("cost_usd", 0.0)
    is_error = data.get("is_error", False)
    error_type = data.get("error_type") or data.get("error")

    return ClaudeResponse(
        text=result_text.strip(),
        session_id=session_id,
        cost_usd=cost_usd,
        is_error=is_error,
        raw=data,
        error_type=error_type,
    )
