"""Tool Adapter: MCP Gateway -> Gemini Function Calling bridge.

Thin wrapper around BaseToolAdapter with Gemini-specific tool
conversion, name sanitisation, and result formatting.
"""

import json

from core.runners.tool_adapter import BaseToolAdapter


class ToolAdapter(BaseToolAdapter):
    """Bridge between MCP Gateway and Gemini Function Calling."""

    def __init__(self, gateway_url: str | None = None):
        super().__init__(gateway_url)
        # Gemini function names: [a-zA-Z_][a-zA-Z0-9_]* — no hyphens.
        # Map sanitized names back to original MCP names for gateway calls.
        self._name_map: dict[str, str] = {}

    async def initialize(self, agent_id: str, unified_id: str | None = None) -> None:
        """Set up HTTP session and reset the name map."""
        await super().initialize(agent_id, unified_id)
        self._name_map = {}

    def _resolve_tool_name(self, name: str) -> str:
        """Restore original MCP name (Gemini may have sanitized hyphens)."""
        return self._name_map.get(name, name)

    @staticmethod
    def _sanitize_name(name: str) -> str:
        """Sanitize tool name for Gemini (only [a-zA-Z0-9_] allowed)."""
        return name.replace("-", "_")

    def mcp_to_gemini_declarations(self, tools: list[dict]) -> list[dict]:
        """Convert MCP tool definitions to Gemini function declarations.

        Returns a list of dicts suitable for google.genai types.Tool.
        Sanitizes tool names (hyphens -> underscores) and maintains a
        reverse map for restoring original names during call_tool.
        """
        self._name_map = {}
        declarations = []
        for tool in tools:
            original_name = tool.get("name", "")
            safe_name = self._sanitize_name(original_name)
            if safe_name != original_name:
                self._name_map[safe_name] = original_name
            description = tool.get("description", "")
            input_schema = tool.get("inputSchema", {})

            parameters = (
                self._convert_json_schema(input_schema) if input_schema else None
            )

            decl = {
                "name": safe_name,
                "description": description,
            }
            if parameters:
                decl["parameters"] = parameters
            declarations.append(decl)

        return declarations

    def _convert_json_schema(self, schema: dict) -> dict:
        """Convert JSON Schema to Gemini-compatible schema dict.

        Handles the subset of JSON Schema that Gemini supports,
        with fallback to STRING for unsupported constructs.
        """
        if not schema or not isinstance(schema, dict):
            return {}

        result = {}
        json_type = schema.get("type", "")

        type_map = {
            "string": "STRING",
            "number": "NUMBER",
            "integer": "INTEGER",
            "boolean": "BOOLEAN",
            "array": "ARRAY",
            "object": "OBJECT",
        }

        if json_type in type_map:
            result["type"] = type_map[json_type]
        elif "anyOf" in schema or "oneOf" in schema:
            # Unsupported union types — fallback to STRING
            variants = schema.get("anyOf", schema.get("oneOf", []))
            desc = schema.get("description", "")
            desc += f" (accepts: {json.dumps(variants)})"
            return {"type": "STRING", "description": desc.strip()}
        else:
            result["type"] = "STRING"

        if "description" in schema:
            result["description"] = schema["description"]

        if "enum" in schema:
            result["enum"] = schema["enum"]

        if schema.get("nullable"):
            result["nullable"] = True

        # Handle object properties
        if json_type == "object" and "properties" in schema:
            props = {}
            required_fields = schema.get("required", [])
            for prop_name, prop_schema in schema["properties"].items():
                converted = self._convert_json_schema(prop_schema)
                props[prop_name] = converted
            result["properties"] = props
            if required_fields:
                result["required"] = required_fields

        # Handle array items — Gemini requires "items" for ARRAY types
        if json_type == "array":
            if "items" in schema:
                result["items"] = self._convert_json_schema(schema["items"])
            else:
                # Default to STRING when MCP schema omits items
                result["items"] = {"type": "STRING"}

        return result

    def format_tool_result(self, tool_name: str, content: list[dict]) -> dict:
        """Format MCP tool response as Gemini function response content.

        Returns a dict matching Gemini's Content format for function responses.
        """
        text_parts = self._extract_text_parts(content)

        return {
            "role": "function",
            "parts": [
                {
                    "function_response": {
                        "name": tool_name,
                        "response": {"result": "\n".join(text_parts)},
                    }
                }
            ],
        }
