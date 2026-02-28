"""Tool Adapter: MCP Gateway -> OpenAI function calling bridge.

Thin wrapper around BaseToolAdapter with OpenAI-specific tool
conversion and result formatting.
"""

from config.logging_config import logger
from core.runners.tool_adapter import BaseToolAdapter


class ToolAdapter(BaseToolAdapter):
    """Bridge between MCP Gateway and OpenAI function calling."""

    def mcp_to_openai_tools(self, mcp_tools: list[dict]) -> list[dict]:
        """Convert MCP tool definitions to OpenAI function calling format.

        OpenAI wraps tools in {"type": "function", "function": {...}} and
        accepts native JSON Schema for parameters.
        """
        tools = []
        for tool in mcp_tools:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get(
                            "inputSchema", {"type": "object", "properties": {}}
                        ),
                    },
                }
            )
        return tools

    def format_tool_result(
        self,
        tool_call_id: str,
        content: list[dict],
        is_error: bool = False,
    ) -> dict:
        """Format MCP tool response as OpenAI tool message."""
        text = "\n".join(self._extract_text_parts(content))

        # Prefix error text for clarity
        if is_error and text:
            text = f"Error: {text}"

        # Truncate very large tool results to avoid hitting context limits
        max_len = 100_000
        if len(text) > max_len:
            text = text[:max_len] + f"\n... (truncated, {len(text)} chars total)"
            logger.warning(
                "Tool result for %s truncated from %d to %d chars",
                tool_call_id,
                len(text),
                max_len,
            )

        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": text,
        }
