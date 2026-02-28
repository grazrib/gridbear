"""Ollama API Backend using the native /api/chat endpoint.

Uses httpx directly against Ollama's native API, which supports
options.num_ctx, tool calling, and NDJSON streaming natively.
No OpenAI SDK dependency.
"""

import asyncio
import json
import re

import httpx

from config.logging_config import logger
from core.interfaces.runner import RunnerResponse
from plugins.ollama.cost_tracker import calculate_cost
from plugins.ollama.session_manager import SessionManager
from plugins.ollama.tool_adapter import ToolAdapter


class OllamaApiBackend:
    """Ollama native API backend (/api/chat).

    Uses httpx for HTTP requests, supports multi-turn sessions,
    MCP tool calling, and NDJSON streaming.
    """

    def __init__(self, config: dict):
        self.config = config
        self.host = config.get(
            "host", __import__("os").getenv("OLLAMA_URL", "http://localhost:11434")
        )
        self.model = config.get("model", "qwen3:8b")
        self.timeout = config.get("timeout", 300)
        self.max_output_tokens = config.get("max_output_tokens", 4096)
        self.max_tool_iterations = config.get("max_tool_iterations", 10)
        self.max_tools = config.get("max_tools", 0)
        self.context_length = config.get("context_length", 8192)
        self.auto_pull = config.get("auto_pull", True)

        self._client: httpx.AsyncClient | None = None
        self._sessions = SessionManager(ttl_hours=config.get("session_ttl_hours", 4))
        self._tool_adapter = ToolAdapter()
        self._valid_tool_names: set[str] = set()

    async def initialize(self) -> None:
        """Initialize httpx client and verify Ollama connectivity."""
        self._client = httpx.AsyncClient(
            base_url=self.host,
            timeout=httpx.Timeout(self.timeout, connect=10.0),
        )

        await self._sessions.start_cleanup_loop()
        await self._check_health()

        logger.info(
            "Ollama API backend initialized (host=%s, model=%s, ctx=%d, timeout=%ds)",
            self.host,
            self.model,
            self.context_length,
            self.timeout,
        )

    async def shutdown(self) -> None:
        """Cleanup resources."""
        await self._sessions.stop_cleanup_loop()
        await self._tool_adapter.shutdown()
        if self._client:
            await self._client.aclose()
        self._client = None
        logger.info("Ollama API backend shut down")

    async def _check_health(self) -> None:
        """Verify Ollama is running and model is available.

        If auto_pull is enabled and the model is missing, pull it.
        """
        try:
            resp = await self._client.get("/api/tags")
            resp.raise_for_status()
            models = resp.json().get("models", [])
            available = [m["name"] for m in models]

            model_found = any(
                name == self.model or name.startswith(f"{self.model}-")
                for name in available
            )

            if model_found:
                logger.info("Ollama model %s is available", self.model)
                return

            logger.warning(
                "Model %s not found on Ollama. Available: %s",
                self.model,
                available,
            )

            if self.auto_pull:
                await self._pull_model()

        except httpx.ConnectError:
            logger.error(
                "Cannot connect to Ollama at %s — is the service running?",
                self.host,
            )
        except Exception as e:
            logger.error("Ollama health check failed: %s", e)

    async def _pull_model(self) -> None:
        """Pull a model from the Ollama registry."""
        logger.info(
            "Auto-pulling model %s (this may take several minutes)...",
            self.model,
        )
        try:
            async with httpx.AsyncClient(
                base_url=self.host, timeout=httpx.Timeout(600.0)
            ) as client:
                async with client.stream(
                    "POST", "/api/pull", json={"name": self.model}
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            status = data.get("status", "")
                            if "pulling" in status or "downloading" in status:
                                total = data.get("total", 0)
                                completed = data.get("completed", 0)
                                if total > 0:
                                    pct = completed / total * 100
                                    logger.info("Pulling %s: %.1f%%", self.model, pct)
                        except json.JSONDecodeError:
                            pass
            logger.info("Model %s pulled successfully", self.model)
        except Exception as e:
            logger.error("Failed to pull model %s: %s", self.model, e)

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
        """Execute Ollama API call with session, tool, and streaming support."""
        if not self._client:
            msg = "Ollama API client not initialized"
            logger.error(msg)
            if error_callback:
                await error_callback("runner_error", msg)
            return RunnerResponse(text=msg, is_error=True)

        effective_model = model or self.model
        agent_label = agent_id or "default"

        logger.info(
            "[%s] Ollama API call: model=%s, prompt_len=%d",
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

            api_prompt = self._sanitize_prompt_for_api(prompt) if tools else prompt
            messages = self._sessions.get_history(session.session_id)

            # System prompt as first message
            system_prompt = kwargs.get("system_prompt", "")
            if tools:
                system_prompt = self._augment_system_prompt(system_prompt)

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
                            f"Max tool iterations ({self.max_tool_iterations}) reached. "
                            "Request interrupted."
                        )
                        logger.warning("[%s] %s", agent_label, msg)
                        return RunnerResponse(
                            text=msg,
                            session_id=session.session_id,
                            cost_usd=total_cost,
                            is_error=True,
                            raw={
                                "model": effective_model,
                                "runner": "ollama",
                                "iterations": iterations,
                                "reason": "max_tool_iterations",
                            },
                        )

                    # Add assistant message with tool_calls
                    assistant_msg = {
                        "role": "assistant",
                        "content": text or "",
                        "tool_calls": tool_calls,
                    }
                    api_messages.append(assistant_msg)

                    # Execute tool calls and add results
                    tool_results = await self._execute_tool_calls(
                        tool_calls, tool_callback, agent_label
                    )
                    api_messages.extend(tool_results)

                    # Don't stream intermediate tool-loop iterations
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
                "[%s] Ollama API done: in=%d out=%d iters=%d",
                agent_label,
                total_input_tokens,
                total_output_tokens,
                iterations,
            )

            return RunnerResponse(
                text=final_text,
                session_id=session.session_id,
                cost_usd=total_cost,
                raw={
                    "model": effective_model,
                    "runner": "ollama",
                    "tool_iterations": iterations,
                },
            )

        except Exception as e:
            msg = f"Ollama API error: {e}"
            logger.error("[%s] %s", agent_label, msg, exc_info=True)
            if error_callback:
                await error_callback("runner_error", str(e))
            return RunnerResponse(text=msg, is_error=True)

    # --- Internal methods ---

    def _build_request_body(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None,
        stream: bool = False,
    ) -> dict:
        """Build the request body for /api/chat."""
        body = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "options": {
                "num_ctx": self.context_length,
                "num_predict": self.max_output_tokens,
            },
        }

        if tools:
            body["tools"] = tools

        return body

    async def _call_api(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream_callback=None,
    ) -> tuple[str, list[dict] | None, tuple[int, int, float] | None]:
        """Call Ollama native API with retry and optional streaming.

        Returns (text, tool_calls, usage_tuple).
        Single retry on transient connection errors.
        """
        last_error = None

        for attempt in range(2):
            if attempt > 0:
                delay = 2
                logger.info("Ollama API retry after %ds", delay)
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
                err_str = str(e).lower()
                is_transient = any(
                    m in err_str for m in ("timeout", "connection", "503")
                )
                if not is_transient or attempt >= 1:
                    raise
                logger.warning(
                    "Transient Ollama error (attempt %d): %s", attempt + 1, e
                )

        raise last_error  # pragma: no cover

    async def _call_unary(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None,
    ) -> tuple[str, list[dict] | None, tuple[int, int, float] | None]:
        """Non-streaming API call to /api/chat."""
        body = self._build_request_body(model, messages, tools, stream=False)
        resp = await self._client.post("/api/chat", json=body)
        resp.raise_for_status()
        data = resp.json()

        message = data.get("message", {})
        text = message.get("content", "")
        tool_calls = message.get("tool_calls")
        usage_info = self._extract_usage(data, model)

        return text, tool_calls, usage_info

    async def _call_streaming(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None,
        stream_callback,
    ) -> tuple[str, list[dict] | None, tuple[int, int, float] | None]:
        """Streaming API call — NDJSON lines from /api/chat."""
        body = self._build_request_body(model, messages, tools, stream=True)

        accumulated_text = ""
        tool_calls = None
        usage_info = None

        async with self._client.stream("POST", "/api/chat", json=body) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue

                message = chunk.get("message", {})

                # Accumulate text content
                content = message.get("content", "")
                if content:
                    accumulated_text += content
                    try:
                        await stream_callback(accumulated_text)
                    except Exception:
                        pass  # Never interrupt streaming

                # Tool calls come in the final chunk
                if message.get("tool_calls"):
                    tool_calls = message["tool_calls"]

                # Final chunk has usage data
                if chunk.get("done"):
                    usage_info = self._extract_usage(chunk, model)

        return accumulated_text, tool_calls, usage_info

    @staticmethod
    def _extract_usage(data: dict, model: str) -> tuple[int, int, float] | None:
        """Extract token usage from Ollama response.

        Native API uses prompt_eval_count / eval_count.
        """
        in_tok = data.get("prompt_eval_count", 0) or 0
        out_tok = data.get("eval_count", 0) or 0
        if not in_tok and not out_tok:
            return None
        cost = calculate_cost(model, in_tok, out_tok)
        return in_tok, out_tok, cost

    @staticmethod
    def _augment_system_prompt(system_prompt: str) -> str:
        """Add tool use instructions when tools are available.

        The search_tools/execute_discovered_tool workflow is critical
        for non-Claude models.
        """
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
        """Rewrite text-based MCP references for structured function calling."""

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
        """Initialize ToolAdapter and convert MCP tools for Ollama."""
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

            ollama_tools = self._tool_adapter.mcp_to_ollama_tools(mcp_tools)
            if not ollama_tools:
                self._valid_tool_names = set()
                return None

            self._valid_tool_names = {t["function"]["name"] for t in ollama_tools}
            logger.debug(
                "[%s] Loaded %d MCP tools for Ollama", agent_id, len(ollama_tools)
            )
            return ollama_tools
        except Exception as e:
            logger.warning("[%s] Failed to load MCP tools: %s", agent_id, e)
            self._valid_tool_names = set()
            return None

    async def _execute_tool_calls(
        self,
        tool_calls: list[dict],
        tool_callback,
        agent_label: str,
    ) -> list[dict]:
        """Execute tool calls via ToolAdapter and return tool messages.

        Ollama native format: tool_calls = [{"function": {"name": ..., "arguments": ...}}]
        Tool results: {"role": "tool", "content": "..."}
        """
        results = []
        for tc in tool_calls:
            func = tc.get("function", {})
            name = func.get("name", "")
            arguments = func.get("arguments", {})

            logger.info("[%s] Tool call: %s", agent_label, name)

            if self._valid_tool_names and name not in self._valid_tool_names:
                logger.warning(
                    "[%s] Rejected unknown tool '%s' (not in tool definitions)",
                    agent_label,
                    name,
                )
                results.append(
                    {
                        "role": "tool",
                        "content": (
                            f"Error: function '{name}' does not exist. "
                            "Use only functions from the provided definitions."
                        ),
                    }
                )
                continue

            if tool_callback:
                try:
                    await tool_callback(name, arguments)
                except Exception as e:
                    logger.debug("tool_callback error: %s", e)

            content = await self._tool_adapter.call_tool(name, arguments)
            results.append(self._tool_adapter.format_tool_result(content))

        return results
