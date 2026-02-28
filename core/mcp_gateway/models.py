"""ORM models for MCP Gateway — tool usage metrics."""

from core.orm import fields
from core.orm.model import Model


class ToolUsageRecord(Model):
    """Tracks individual MCP tool calls for usage analytics.

    Each row represents one invocation of a tool by an agent.
    Used by the admin dashboard (Phase 3) to show top tools,
    unused tools, and per-agent breakdowns.

    Retention: 90 days (cleanup at startup + weekly).
    """

    _schema = "public"
    _name = "tool_usage"

    agent_name = fields.Text(max_length=64, required=True, index=True)
    tool_name = fields.Text(max_length=128, required=True)
    called_at = fields.DateTime(auto_now_add=True, index=True)
    success = fields.Boolean(default=True)
    duration_ms = fields.Integer()
