"""Tool Adapter: MCP Gateway -> Ollama native function calling bridge.

Thin wrapper around BaseToolAdapter with Ollama-specific tool
conversion and result formatting.  Ollama uses the same tool definition
format as OpenAI but tool results are simpler (no tool_call_id needed).
"""

from config.logging_config import logger
from core.runners.tool_adapter import BaseToolAdapter


class ToolAdapter(BaseToolAdapter):
    """Bridge between MCP Gateway and Ollama native function calling."""

    def mcp_to_ollama_tools(self, mcp_tools: list[dict]) -> list[dict]:
        """Convert MCP tool definitions to Ollama tool format.

        Ollama uses the same format as OpenAI:
        {"type": "function", "function": {name, description, parameters}}.
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
        content: list[dict],
        is_error: bool = False,
    ) -> dict:
        """Format MCP tool response as Ollama native tool message.

        Ollama native API doesn't require tool_call_id — just
        {"role": "tool", "content": "..."}.
        """
        text = "\n".join(self._extract_text_parts(content))

        if is_error and text:
            text = f"Error: {text}"

        max_len = 100_000
        if len(text) > max_len:
            text = text[:max_len] + f"\n... (truncated, {len(text)} chars total)"
            logger.warning(
                "Tool result truncated from %d to %d chars",
                len(text),
                max_len,
            )

        return {
            "role": "tool",
            "content": text,
        }
