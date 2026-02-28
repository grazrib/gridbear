"""Tool Adapter: MCP Gateway -> Claude tool_use bridge.

Thin wrapper around BaseToolAdapter with Claude-specific tool
conversion and result formatting.
"""

from config.logging_config import logger
from core.runners.tool_adapter import BaseToolAdapter


class ToolAdapter(BaseToolAdapter):
    """Bridge between MCP Gateway and Claude tool_use."""

    def mcp_to_claude_tools(self, mcp_tools: list[dict]) -> list[dict]:
        """Convert MCP tool definitions to Claude tool format.

        Claude accepts native JSON Schema in input_schema, so this is
        simpler than Gemini's conversion — just a field rename.
        """
        tools = []
        for tool in mcp_tools:
            tools.append(
                {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "input_schema": tool.get(
                        "inputSchema", {"type": "object", "properties": {}}
                    ),
                }
            )
        return tools

    def format_tool_result(
        self,
        tool_use_id: str,
        content: list[dict],
        is_error: bool = False,
    ) -> dict:
        """Format MCP tool response as Claude tool_result content block."""
        text = "\n".join(self._extract_text_parts(content))

        # Truncate very large tool results to avoid hitting context limits
        max_len = 100_000
        if len(text) > max_len:
            text = text[:max_len] + f"\n... (truncated, {len(text)} chars total)"
            logger.warning(
                "Tool result for %s truncated from %d to %d chars",
                tool_use_id,
                len(text),
                max_len,
            )

        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": text,
            "is_error": is_error,
        }
