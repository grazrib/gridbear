"""Mistral API Backend using the Chat Completions API.

Direct API calls via httpx, supporting multi-turn sessions,
MCP tool calling via function calling, and SSE streaming.
Mistral's API is OpenAI-compatible.
"""

import asyncio
import json
import os
import re

import httpx

from config.logging_config import logger
from core.interfaces.runner import RunnerResponse
from plugins.mistral.cost_tracker import calculate_cost
from plugins.mistral.session_manager import SessionManager
from plugins.mistral.tool_adapter import ToolAdapter
from ui.secrets_manager import secrets_manager

MISTRAL_API_BASE = "https://api.mistral.ai/v1"
CODESTRAL_API_BASE = "https://codestral.mistral.ai/v1"

# Transient error substrings that warrant retry
_TRANSIENT_ERRORS = (
    "overloaded",
    "rate limit",
    "rate_limit",
    "529",
    "429",
    "503",
    "timeout",
    "connection",
    "server_error",
)


def resolve_model(name: str) -> str:
    """Map model names via registry, passthrough for unknown IDs."""
    from core.registry import get_models_registry

    registry = get_models_registry()
    if registry:
        model_map = registry.get_model_map("mistral")
        if model_map:
            return model_map.get(name, name)
    return name


class MistralApiBackend:
    """Mistral Chat Completions API backend.

    Follows the same structure as OpenAIApiBackend: session management,
    tool loop, streaming, retry with exponential backoff.
    """

    def __init__(self, config: dict, base_url: str = "", api_key_name: str = ""):
        self.config = config
        self.model = config.get(
            "model", os.getenv("MISTRAL_MODEL", "mistral-large-latest")
        )
        self.timeout = int(config.get("timeout", 120))
        self.max_output_tokens = int(config.get("max_output_tokens", 8192))
        self.max_tool_iterations = int(config.get("max_tool_iterations", 20))
        self.max_retries = int(config.get("max_retries", 2))
        self.max_tools = int(config.get("max_tools", 0))  # 0 = unlimited
        self._base_url = base_url or MISTRAL_API_BASE
        self._api_key_name = api_key_name or "MISTRAL_API_KEY"

        self._client: httpx.AsyncClient | None = None
        self._api_key: str | None = None
        self._sessions = SessionManager(ttl_hours=config.get("session_ttl_hours", 4))
        self._tool_adapter = ToolAdapter()
        self._valid_tool_names: set[str] = set()

    async def initialize(self) -> None:
        """Initialize the httpx client and session cleanup."""
        self._api_key = secrets_manager.get_plain(self._api_key_name)
        if not self._api_key:
            logger.error(
                "%s not set — Mistral API backend disabled", self._api_key_name
            )
            return

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            timeout=self.timeout,
        )
        await self._sessions.start_cleanup_loop()
        logger.info(
            "Mistral API backend initialized (model=%s, base=%s, timeout=%ds)",
            self.model,
            self._base_url,
            self.timeout,
        )

    async def shutdown(self) -> None:
        """Cleanup resources."""
        await self._sessions.stop_cleanup_loop()
        await self._tool_adapter.shutdown()
        if self._client:
            await self._client.aclose()
        self._client = None
        logger.info("Mistral API backend shut down")

    async def run(
        self,
        prompt: str,
        session_id: str | None = None,
        progress_callback=None,
        error_callback=None,
        tool_callback=None,
        stream_callback=None,
        agent_id: str | None = None,
        model: str | None = None,
        no_tools: bool = False,
        **kwargs,
    ) -> RunnerResponse:
        """Execute Mistral API call with session, tool, and streaming support."""
        if not self._client:
            msg = "Mistral API client not initialized (missing MISTRAL_API_KEY?)"
            logger.error(msg)
            if error_callback:
                await error_callback("runner_error", msg)
            return RunnerResponse(text=msg, is_error=True)

        effective_model = resolve_model(model or self.model)
        agent_label = agent_id or "default"

        logger.info(
            "[%s] Mistral API call: model=%s, prompt_len=%d",
            agent_label,
            effective_model,
            len(prompt),
        )

        try:
            # --- Session management ---
            session = self._sessions.get_or_create(session_id, agent_label)

            # --- Tool setup ---
            unified_id = kwargs.get("unified_id")
            agent_max_tools = kwargs.get("max_tools")
            agent_tool_loading = kwargs.get("tool_loading", "full")
            tools = None
            if not no_tools and agent_id:
                tools = await self._setup_tools(
                    agent_id,
                    unified_id,
                    agent_max_tools,
                    tool_loading=agent_tool_loading,
                )

            # Sanitize prompt when tools are loaded
            api_prompt = self._sanitize_prompt_for_api(prompt) if tools else prompt
            messages = self._sessions.get_history(session.session_id)

            # System prompt as first message
            system_prompt = kwargs.get("system_prompt", "")
            if tools:
                system_prompt = self._augment_system_prompt(system_prompt)

            # Build messages: system + history + new user message
            api_messages = []
            if system_prompt:
                api_messages.append({"role": "system", "content": system_prompt})
            api_messages.extend(messages)
            api_messages.append({"role": "user", "content": api_prompt})

            # --- API call with tool loop ---
            total_cost = 0.0
            total_input_tokens = 0
            total_output_tokens = 0
            iterations = 0

            while True:
                text, tool_calls, usage_info = await self._call_api(
                    model=effective_model,
                    messages=api_messages,
                    tools=tools,
                    stream_callback=stream_callback,
                )

                if usage_info:
                    in_tok, out_tok, cost = usage_info
                    total_input_tokens += in_tok
                    total_output_tokens += out_tok
                    total_cost += cost

                if tool_calls and not no_tools:
                    iterations += 1
                    if iterations > self.max_tool_iterations:
                        msg = (
                            f"Max tool iterations ({self.max_tool_iterations}) "
                            "reached. Request interrupted."
                        )
                        logger.warning("[%s] %s", agent_label, msg)
                        return RunnerResponse(
                            text=msg,
                            session_id=session.session_id,
                            cost_usd=total_cost,
                            is_error=True,
                            raw={
                                "model": effective_model,
                                "runner": "mistral-api",
                                "iterations": iterations,
                                "reason": "max_tool_iterations",
                            },
                        )

                    # Add assistant message with tool_calls
                    assistant_msg = {"role": "assistant", "content": text or None}
                    assistant_msg["tool_calls"] = [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": (
                                    json.dumps(tc["arguments"])
                                    if isinstance(tc["arguments"], dict)
                                    else tc["arguments"]
                                ),
                            },
                        }
                        for tc in tool_calls
                    ]
                    api_messages.append(assistant_msg)

                    # Execute and append results
                    tool_results = await self._execute_tool_calls(
                        tool_calls, tool_callback, agent_label
                    )
                    api_messages.extend(tool_results)

                    # Don't stream intermediate iterations
                    stream_callback = None
                    continue

                break

            # Update session
            final_text = text or ""
            self._sessions.append_turn(session.session_id, "user", prompt)
            self._sessions.append_turn(session.session_id, "assistant", final_text)
            self._sessions.update_usage(
                session.session_id,
                total_input_tokens,
                total_output_tokens,
                total_cost,
            )

            logger.info(
                "[%s] Mistral API done: in=%d out=%d cost=$%.6f iters=%d",
                agent_label,
                total_input_tokens,
                total_output_tokens,
                total_cost,
                iterations,
            )

            return RunnerResponse(
                text=final_text,
                session_id=session.session_id,
                cost_usd=total_cost,
                raw={
                    "model": effective_model,
                    "runner": "mistral-api",
                    "tool_iterations": iterations,
                },
            )

        except Exception as e:
            msg = f"Mistral API error: {e}"
            logger.error("[%s] %s", agent_label, msg, exc_info=True)
            if error_callback:
                await error_callback("runner_error", str(e))
            return RunnerResponse(text=msg, is_error=True)

    # --- Internal methods ---

    async def _call_api(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream_callback=None,
    ) -> tuple[str, list[dict] | None, tuple[int, int, float] | None]:
        """Call Mistral API with retry and optional streaming.

        Returns (text, tool_calls, usage_tuple).
        """
        last_error = None

        for attempt in range(1 + self.max_retries):
            if attempt > 0:
                delay = 2**attempt
                logger.info(
                    "Mistral API retry %d/%d after %ds",
                    attempt,
                    self.max_retries,
                    delay,
                )
                await asyncio.sleep(delay)

            try:
                if stream_callback:
                    return await self._call_streaming(
                        model, messages, tools, stream_callback
                    )
                else:
                    return await self._call_unary(model, messages, tools)
            except Exception as e:
                last_error = e
                if not self._is_transient_error(e) or attempt >= self.max_retries:
                    raise
                logger.warning(
                    "Transient Mistral API error (attempt %d): %s", attempt + 1, e
                )

        raise last_error  # pragma: no cover

    def _build_request_body(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None,
        stream: bool = False,
    ) -> dict:
        """Build request body for chat/completions."""
        body = {
            "model": model,
            "messages": messages,
            "max_tokens": self.max_output_tokens,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if stream:
            body["stream"] = True
            body["stream_options"] = {"include_usage": True}
        return body

    async def _call_unary(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None,
    ) -> tuple[str, list[dict] | None, tuple[int, int, float] | None]:
        """Non-streaming API call."""
        body = self._build_request_body(model, messages, tools)
        resp = await self._client.post("/chat/completions", json=body)
        resp.raise_for_status()
        data = resp.json()

        message = data["choices"][0]["message"]
        text = message.get("content") or ""
        tool_calls = self._extract_tool_calls(message)
        usage_info = self._extract_usage(data, model)

        return text, tool_calls, usage_info

    async def _call_streaming(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None,
        stream_callback,
    ) -> tuple[str, list[dict] | None, tuple[int, int, float] | None]:
        """Streaming API call — SSE parsing."""
        body = self._build_request_body(model, messages, tools, stream=True)

        accumulated_text = ""
        tool_calls_acc: dict[int, dict] = {}
        usage_info = None

        async with self._client.stream("POST", "/chat/completions", json=body) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload == "[DONE]":
                    break

                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue

                # Usage in final chunk
                if chunk.get("usage"):
                    usage = chunk["usage"]
                    in_tok = usage.get("prompt_tokens", 0)
                    out_tok = usage.get("completion_tokens", 0)
                    cost = calculate_cost(model, in_tok, out_tok)
                    usage_info = (in_tok, out_tok, cost)

                choices = chunk.get("choices", [])
                if not choices:
                    continue

                delta = choices[0].get("delta", {})

                # Accumulate text
                if delta.get("content"):
                    accumulated_text += delta["content"]
                    try:
                        await stream_callback(accumulated_text)
                    except Exception:
                        pass

                # Accumulate tool calls
                if delta.get("tool_calls"):
                    for tc_delta in delta["tool_calls"]:
                        idx = tc_delta.get("index", 0)
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {
                                "id": tc_delta.get("id", ""),
                                "name": "",
                                "arguments": "",
                            }
                        entry = tool_calls_acc[idx]
                        if tc_delta.get("id"):
                            entry["id"] = tc_delta["id"]
                        fn = tc_delta.get("function", {})
                        if fn.get("name"):
                            entry["name"] = fn["name"]
                        if fn.get("arguments"):
                            entry["arguments"] += fn["arguments"]

        # Parse tool call arguments
        tool_calls = None
        if tool_calls_acc:
            tool_calls = []
            for idx in sorted(tool_calls_acc):
                tc = tool_calls_acc[idx]
                try:
                    tc["arguments"] = json.loads(tc["arguments"])
                except (json.JSONDecodeError, TypeError):
                    tc["arguments"] = {}
                tool_calls.append(tc)

        return accumulated_text, tool_calls, usage_info

    @staticmethod
    def _augment_system_prompt(system_prompt: str) -> str:
        """Add tool use instructions when tools are available."""
        tool_instruction = (
            "\n\n[CRITICAL - Tool Use Protocol]\n"
            "You have function calling capabilities available via the API.\n"
            "ALL services (image generation, collaboration, Odoo, HomeAssistant, "
            "Gmail, GitHub, calendars, etc.) are available as function calls. "
            "NEVER write tool names or function calls as text in your response. "
            "Use the function definitions provided to you.\n"
            "If you need to generate an image, start a collaboration, query Odoo, "
            "or use any other service, invoke the corresponding function.\n\n"
            "[CRITICAL - search_tools / execute_discovered_tool workflow]\n"
            "When you see search_tools and execute_discovered_tool functions:\n"
            "1. Call search_tools with a keyword query to find the right tool.\n"
            "2. The result contains tool entries with name, description, and "
            "inputSchema (the parameters the tool accepts).\n"
            "3. Call execute_discovered_tool with TWO fields:\n"
            '   - "tool_name": the exact tool name from the search results\n'
            '   - "arguments": an object with the parameters described in '
            "the tool's inputSchema\n"
            "IMPORTANT: You MUST read the inputSchema from the search results "
            "and fill in the arguments accordingly. Do NOT leave arguments empty.\n"
            "Example: if search_tools returns a tool named 'odoo-mcp__search' "
            "with inputSchema requiring 'model' (string), you must call:\n"
            "  execute_discovered_tool(tool_name='odoo-mcp__search', "
            "arguments={'model': 'res.partner', 'domain': []})"
        )
        return (
            (system_prompt + tool_instruction)
            if system_prompt
            else tool_instruction.strip()
        )

    @staticmethod
    def _sanitize_prompt_for_api(prompt: str) -> str:
        """Rewrite text-based MCP references for structured function calling.

        Same sanitization as OpenAI — prevents text-based tool mimicry.
        """

        def _rewrite_mcp_permissions(match: re.Match) -> str:
            block = match.group(0)
            servers = re.findall(r"'([^']+)'", block)
            if not servers:
                if "NO access" in block:
                    return (
                        "[Permissions: This user has no access to external "
                        "services. Do not call any external service functions.]"
                    )
                return ""

            readable = []
            for s in servers:
                if s.startswith("gmail-"):
                    readable.append(f"Gmail ({s[6:]})")
                elif s.startswith("gws-"):
                    readable.append(f"Google Workspace ({s[4:]})")
                elif s.startswith("ms365-"):
                    readable.append(f"Microsoft 365 ({s[6:]})")
                elif s == "odoo-mcp":
                    readable.append("Odoo")
                elif s == "homeassistant":
                    readable.append("HomeAssistant")
                elif s == "playwright":
                    readable.append("Web Browser (Playwright)")
                elif s == "github":
                    readable.append("GitHub")
                else:
                    clean = s.replace("-mcp", "").replace("-", " ").title()
                    readable.append(clean)

            services = ", ".join(readable)
            return (
                f"[Available Services: This user can access: {services}. "
                f"Use the corresponding function calls for these services. "
                f"Do not call functions for services not listed.]"
            )

        prompt = re.sub(r"\[MCP Permissions:[^\]]*\]", _rewrite_mcp_permissions, prompt)
        prompt = re.sub(r"\[Built-in Tools:[^\]]*\]", "", prompt)
        prompt = re.sub(r"mcp__[\w-]+__\w+(?:\s+with\s+[^\n]*)?", "", prompt)
        prompt = re.sub(
            r"usa il tool MCP `[^`]+`", "usa la funzione appropriata", prompt
        )
        prompt = re.sub(r"\n{3,}", "\n\n", prompt)

        return prompt

    async def _setup_tools(
        self,
        agent_id: str,
        unified_id: str | None = None,
        agent_max_tools: int | None = None,
        tool_loading: str = "full",
    ) -> list[dict] | None:
        """Initialize ToolAdapter and convert MCP tools for Mistral."""
        try:
            await self._tool_adapter.initialize(agent_id, unified_id=unified_id)
            effective_max = agent_max_tools or self.max_tools or None
            mcp_tools = await self._tool_adapter.list_tools(
                tool_budget=effective_max,
                tool_loading=tool_loading,
            )
            if not mcp_tools:
                self._valid_tool_names = set()
                return None

            if effective_max and len(mcp_tools) > effective_max:
                logger.warning(
                    "[%s] Runner safety net: MCP tools (%d) exceed max_tools (%d)",
                    agent_id,
                    len(mcp_tools),
                    effective_max,
                )
                mcp_tools = mcp_tools[:effective_max]

            mistral_tools = self._tool_adapter.mcp_to_mistral_tools(mcp_tools)
            if not mistral_tools:
                self._valid_tool_names = set()
                return None

            self._valid_tool_names = {t["function"]["name"] for t in mistral_tools}
            logger.debug("[%s] Loaded %d MCP tools", agent_id, len(mistral_tools))
            return mistral_tools
        except Exception as e:
            logger.warning("[%s] Failed to load MCP tools: %s", agent_id, e)
            self._valid_tool_names = set()
            return None

    @staticmethod
    def _extract_tool_calls(message: dict) -> list[dict] | None:
        """Extract tool calls from Mistral response message."""
        tool_calls_raw = message.get("tool_calls")
        if not tool_calls_raw:
            return None
        calls = []
        for tc in tool_calls_raw:
            fn = tc.get("function", {})
            arguments = fn.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except (json.JSONDecodeError, TypeError):
                    arguments = {}
            calls.append(
                {
                    "id": tc.get("id", ""),
                    "name": fn.get("name", ""),
                    "arguments": arguments,
                }
            )
        return calls if calls else None

    @staticmethod
    def _extract_usage(data: dict, model: str) -> tuple[int, int, float] | None:
        """Extract token usage and cost from response."""
        usage = data.get("usage")
        if not usage:
            return None
        in_tok = usage.get("prompt_tokens", 0)
        out_tok = usage.get("completion_tokens", 0)
        cost = calculate_cost(model, in_tok, out_tok)
        return in_tok, out_tok, cost

    async def _execute_tool_calls(
        self,
        tool_calls: list[dict],
        tool_callback,
        agent_label: str,
    ) -> list[dict]:
        """Execute tool calls via ToolAdapter and return tool messages."""
        results = []
        for tc in tool_calls:
            tool_id = tc["id"]
            name = tc["name"]
            arguments = tc["arguments"]

            logger.info("[%s] Tool call: %s", agent_label, name)

            if self._valid_tool_names and name not in self._valid_tool_names:
                logger.warning(
                    "[%s] Rejected unknown tool '%s' (not in tool definitions)",
                    agent_label,
                    name,
                )
                content = [
                    {
                        "type": "text",
                        "text": (
                            f"Error: function '{name}' does not exist. "
                            "Use only functions from the provided definitions."
                        ),
                    }
                ]
                results.append(
                    self._tool_adapter.format_tool_result(
                        tool_id, content, is_error=True
                    )
                )
                continue

            if tool_callback:
                try:
                    await tool_callback(name, arguments)
                except Exception as e:
                    logger.debug("tool_callback error: %s", e)

            content = await self._tool_adapter.call_tool(name, arguments)
            results.append(self._tool_adapter.format_tool_result(tool_id, content))

        return results

    @staticmethod
    def _is_transient_error(error: Exception) -> bool:
        """Check if an error is transient and worth retrying."""
        error_str = str(error).lower()
        return any(marker in error_str for marker in _TRANSIENT_ERRORS)
