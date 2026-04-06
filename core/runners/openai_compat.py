"""OpenAI-compatible runner base for third-party providers.

Shared implementation reused by: openrouter, deepseek, cerebras, huggingface.
Each provider subclasses OpenAICompatibleRunner and overrides:
  - base_url: str           — API base URL
  - _get_api_key() -> str   — how to fetch the API key from vault
  - _extra_headers() -> dict — optional extra HTTP headers
  - _supports_tools(model) -> bool
"""

import asyncio
import json
import re
from typing import Any

import httpx

from config.logging_config import logger
from core.interfaces.runner import BaseRunner, RunnerResponse
from core.runners.tool_adapter import BaseToolAdapter


class OpenAICompatToolAdapter(BaseToolAdapter):
    """Bridge between MCP Gateway and OpenAI-compatible function calling."""

    def mcp_to_tools(self, mcp_tools: list[dict]) -> list[dict]:
        """Convert MCP tool definitions to OpenAI function calling format."""
        return [
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
            for tool in mcp_tools
        ]

    def format_tool_result(
        self,
        content: list[dict],
        tool_call_id: str = "call_0",
        is_error: bool = False,
    ) -> dict:
        """Format MCP tool response as OpenAI-compatible tool message."""
        text = "\n".join(self._extract_text_parts(content))
        if is_error and text:
            text = f"Error: {text}"
        max_len = 100_000
        if len(text) > max_len:
            text = text[:max_len] + f"\n... (truncated, {len(text)} chars total)"
        return {"role": "tool", "tool_call_id": tool_call_id, "content": text}


class OpenAICompatibleRunner(BaseRunner):
    """Base runner for any OpenAI-compatible API endpoint."""

    name = "openai_compat"
    base_url: str = ""

    def __init__(self, config: dict):
        super().__init__(config)
        self.model = config.get("model", "")
        self.timeout = config.get("timeout", 120)
        self.temperature = config.get("temperature", 0.7)
        self.max_output_tokens = config.get("max_output_tokens", 8192)
        self.max_tool_iterations = config.get("max_tool_iterations", 20)
        self.max_tools = config.get("max_tools", 0)
        self.notify_tool_use = config.get("notify_tool_use", True)

        self._client: httpx.AsyncClient | None = None
        self._tool_adapter = OpenAICompatToolAdapter()
        self._valid_tool_names: set[str] = set()
        self._sessions: dict[str, list[dict]] = {}

    def _get_api_key(self) -> str:
        """Override in subclass to return the provider API key."""
        raise NotImplementedError

    def _extra_headers(self) -> dict:
        """Override in subclass to add provider-specific headers."""
        return {}

    def _supports_tools(self, model: str) -> bool:
        """Override in subclass if some models don't support tool calling."""
        return True

    async def initialize(self) -> None:
        api_key = self._get_api_key()
        if not api_key:
            logger.error("%s: API key not found in vault — runner disabled", self.name)
            return
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            **self._extra_headers(),
        }
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=httpx.Timeout(self.timeout, connect=10.0),
        )
        logger.info(
            "%s runner initialized (model=%s, url=%s)", self.name, self.model, self.base_url
        )

    async def shutdown(self) -> None:
        await self._tool_adapter.shutdown()
        if self._client:
            await self._client.aclose()
        self._client = None
        self._sessions.clear()
        logger.info("%s runner shut down", self.name)

    async def supports_tools(self) -> bool:
        return True

    async def supports_vision(self) -> bool:
        return False

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
        if not self._client:
            msg = f"{self.name} client not initialized (missing API key in vault?)"
            logger.error(msg)
            if error_callback:
                await error_callback("runner_error", msg)
            return RunnerResponse(text=msg, is_error=True)

        effective_model = model or self.model
        agent_label = agent_id or "default"
        if not session_id:
            session_id = f"{self.name}-{agent_label}-{id(prompt)}"
        history = self._sessions.setdefault(session_id, [])

        try:
            # Tool setup
            unified_id = kwargs.get("unified_id")
            agent_max_tools = kwargs.get("max_tools")
            tools = None
            if not no_tools and agent_id and self._supports_tools(effective_model):
                tools = await self._setup_tools(agent_id, unified_id, agent_max_tools)

            # Build messages
            system_prompt = kwargs.get("system_prompt", "")
            if tools:
                system_prompt = self._augment_system_prompt(system_prompt)

            api_messages: list[dict] = []
            if system_prompt:
                api_messages.append({"role": "system", "content": system_prompt})
            api_messages.extend(history)
            api_prompt = self._sanitize_prompt(prompt) if tools else prompt
            api_messages.append({"role": "user", "content": api_prompt})

            # Tool loop
            total_input = 0
            total_output = 0
            iterations = 0

            while True:
                text, tool_calls, usage = await self._call_api(
                    model=effective_model,
                    messages=api_messages,
                    tools=tools,
                    stream_callback=stream_callback,
                )
                if usage:
                    total_input += usage.get("prompt_tokens", 0)
                    total_output += usage.get("completion_tokens", 0)

                if tool_calls and not no_tools:
                    iterations += 1
                    if iterations > self.max_tool_iterations:
                        msg = f"Max tool iterations ({self.max_tool_iterations}) reached."
                        return RunnerResponse(
                            text=msg, session_id=session_id, is_error=True,
                            raw={"model": effective_model, "runner": self.name}
                        )
                    api_messages.append({
                        "role": "assistant",
                        "content": text or "",
                        "tool_calls": tool_calls,
                    })
                    results = await self._execute_tool_calls(tool_calls, tool_callback, agent_label)
                    api_messages.extend(results)
                    stream_callback = None
                    continue
                break

            # Save session
            history.append({"role": "user", "content": prompt})
            history.append({"role": "assistant", "content": text or ""})
            if len(history) > 40:
                self._sessions[session_id] = history[-40:]

            logger.info(
                "[%s] %s done: in=%d out=%d iters=%d",
                agent_label, self.name, total_input, total_output, iterations
            )
            return RunnerResponse(
                text=text or "",
                session_id=session_id,
                raw={"model": effective_model, "runner": self.name, "tool_iterations": iterations},
            )

        except Exception as e:
            msg = f"{self.name} API error: {e}"
            logger.error("[%s] %s", agent_label, msg, exc_info=True)
            if error_callback:
                await error_callback("runner_error", str(e))
            return RunnerResponse(text=msg, is_error=True)

    async def _call_api(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream_callback=None,
    ) -> tuple[str, list | None, dict | None]:
        """Call /chat/completions endpoint. Returns (text, tool_calls, usage)."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_output_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        last_error: Exception | None = None
        for attempt in range(3):
            if attempt > 0:
                await asyncio.sleep(2 ** attempt)
                logger.info("%s retry %d", self.name, attempt)
            try:
                if stream_callback and not tools:
                    return await self._stream(payload, stream_callback)
                resp = await self._client.post("/chat/completions", json=payload)
                resp.raise_for_status()
                data = resp.json()
                choice = data["choices"][0]
                text = choice["message"].get("content") or ""
                tool_calls = None
                raw_tcs = choice["message"].get("tool_calls")
                if raw_tcs:
                    tool_calls = [
                        {
                            "id": tc.get("id", "call_0"),
                            "type": "function",
                            "function": {
                                "name": tc["function"]["name"],
                                "arguments": tc["function"].get("arguments", "{}"),
                            },
                        }
                        for tc in raw_tcs
                    ]
                usage = data.get("usage")
                return text, tool_calls, usage
            except Exception as e:
                last_error = e
                err = str(e).lower()
                transient = any(m in err for m in ("timeout", "503", "connection", "429"))
                if not transient or attempt >= 2:
                    raise
                logger.warning("%s transient error (attempt %d): %s", self.name, attempt + 1, e)

        raise last_error  # pragma: no cover

    async def _stream(self, payload: dict, stream_callback) -> tuple[str, None, None]:
        """Streaming SSE call."""
        payload = {**payload, "stream": True}
        accumulated = ""
        async with self._client.stream("POST", "/chat/completions", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk["choices"][0]["delta"]
                    content = delta.get("content", "")
                    if content:
                        accumulated += content
                        try:
                            await stream_callback(accumulated)
                        except Exception:
                            pass
                except (json.JSONDecodeError, KeyError):
                    continue
        return accumulated, None, None

    async def _setup_tools(
        self,
        agent_id: str,
        unified_id: str | None,
        agent_max_tools: int | None,
    ) -> list[dict] | None:
        try:
            await self._tool_adapter.initialize(agent_id, unified_id=unified_id)
            effective_max = agent_max_tools or self.max_tools or None
            mcp_tools = await self._tool_adapter.list_tools(tool_budget=effective_max)
            if not mcp_tools:
                self._valid_tool_names = set()
                return None
            if effective_max and len(mcp_tools) > effective_max:
                mcp_tools = mcp_tools[:effective_max]
            tools = self._tool_adapter.mcp_to_tools(mcp_tools)
            self._valid_tool_names = {t["function"]["name"] for t in tools}
            logger.info("[%s] Loaded %d MCP tools for %s", agent_id, len(tools), self.name)
            return tools
        except Exception as e:
            logger.warning("[%s] Failed to load MCP tools: %s", agent_id, e)
            self._valid_tool_names = set()
            return None

    async def _execute_tool_calls(
        self, tool_calls: list[dict], tool_callback, agent_label: str
    ) -> list[dict]:
        results = []
        for tc in tool_calls:
            func = tc.get("function", {})
            name = func.get("name", "")
            tool_call_id = tc.get("id", "call_0")
            raw_args = func.get("arguments", "{}")
            arguments = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})

            if self._valid_tool_names and name not in self._valid_tool_names:
                logger.warning("[%s] Rejected unknown tool '%s'", agent_label, name)
                results.append({
                    "role": "tool", "tool_call_id": tool_call_id,
                    "content": f"Error: function '{name}' is not available.",
                })
                continue

            logger.info("[%s] Tool call: %s", agent_label, name)
            if tool_callback:
                try:
                    await tool_callback(name, arguments)
                except Exception as e:
                    logger.debug("tool_callback error: %s", e)

            content = await self._tool_adapter.call_tool(name, arguments)
            results.append(self._tool_adapter.format_tool_result(content, tool_call_id))
        return results

    @staticmethod
    def _augment_system_prompt(sp: str) -> str:
        instr = (
            "\n\n[CRITICAL - Function Calling Protocol]\n"
            "You have structured function calling tools available.\n"
            "ALL services (Odoo, HomeAssistant, Gmail, GitHub, etc.) are available "
            "as function calls. NEVER write tool names as text — use the function "
            "declarations provided. When you need Odoo data, call odoo_search_read, "
            "odoo_create, etc. directly. Always fill required arguments."
        )
        return (sp + instr) if sp else instr.strip()

    @staticmethod
    def _sanitize_prompt(prompt: str) -> str:
        prompt = re.sub(r"\[MCP Permissions:[^\]]*\]", "", prompt)
        prompt = re.sub(r"\[Built-in Tools:[^\]]*\]", "", prompt)
        prompt = re.sub(r"mcp__[\w-]+__\w+(?:\s+with\s+[^\n]*)?", "", prompt)
        return re.sub(r"\n{3,}", "\n\n", prompt)
