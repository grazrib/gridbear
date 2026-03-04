"""Tool Adapter: MCP Gateway -> Mistral function calling bridge.

Thin wrapper around BaseToolAdapter with Mistral-specific tool
conversion and result formatting. Mistral uses OpenAI-compatible
function calling format.
"""

from config.logging_config import logger
from core.runners.tool_adapter import BaseToolAdapter


class ToolAdapter(BaseToolAdapter):
    """Bridge between MCP Gateway and Mistral function calling."""

    def mcp_to_mistral_tools(self, mcp_tools: list[dict]) -> list[dict]:
        """Convert MCP tool definitions to Mistral function calling format.

        Mistral uses the same format as OpenAI: wraps tools in
        {"type": "function", "function": {...}} with native JSON Schema
        for parameters.
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
        """Format MCP tool response as Mistral tool message."""
        text = "\n".join(self._extract_text_parts(content))

        if is_error and text:
            text = f"Error: {text}"

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
