"""Groq Runner Plugin.

Ultra-fast cloud LLM inference via Groq's LPU hardware.
Uses the Groq Python SDK (OpenAI-compatible API).

Free tier: 14,400 requests/day, 6,000 tokens/min for most models.
Models with tool calling: llama-3.3-70b-versatile, llama3-70b-8192,
  qwen-qwq-32b, mistral-saba-24b, compound-beta, compound-beta-mini.

MCP tool access is handled by the MCP Gateway (gridbear-ui):
- Each agent has a pre-provisioned OAuth2 token
- ToolAdapter calls the gateway via HTTP JSON-RPC
- Tools use OpenAI-compatible function calling format (same as Ollama)
"""

import asyncio
import json
import os
import re
from typing import Any

from config.logging_config import logger
from core.interfaces.runner import BaseRunner, RunnerResponse
from core.runners.tool_adapter import BaseToolAdapter
from ui.secrets_manager import secrets_manager

# Groq models that support tool/function calling
_TOOL_CAPABLE_MODELS = {
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "llama3-70b-8192",
    "llama3-8b-8192",
    "gemma2-9b-it",
    "mixtral-8x7b-32768",
    "mistral-saba-24b",
    "compound-beta",
    "compound-beta-mini",
    # qwen-qwq-32b supports tool calling in non-thinking mode
    "qwen-qwq-32b",
}

# Transient errors that warrant a retry
_TRANSIENT_ERRORS = ("rate_limit_exceeded", "503", "timeout", "connection", "429")


class GroqToolAdapter(BaseToolAdapter):
    """Bridge between MCP Gateway and Groq function calling.

    Groq uses the same OpenAI tool format as Ollama:
    {"type": "function", "function": {name, description, parameters}}
    Tool results: {"role": "tool", "tool_call_id": ..., "content": "..."}
    """

    def mcp_to_groq_tools(self, mcp_tools: list[dict]) -> list[dict]:
        """Convert MCP tool definitions to Groq/OpenAI function calling format."""
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
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": text,
        }


class GroqRunner(BaseRunner):
    """Groq cloud LLM runner — ultra-fast inference via LPU hardware."""

    name = "groq"

    _DEFAULT_MODELS = [
        {"id": "llama-3.3-70b-versatile", "name": "Llama 3.3 70B Versatile (recommended)"},
        {"id": "llama-3.1-8b-instant", "name": "Llama 3.1 8B Instant (fastest)"},
        {"id": "qwen-qwq-32b", "name": "Qwen QwQ 32B (reasoning)"},
        {"id": "mistral-saba-24b", "name": "Mistral Saba 24B"},
        {"id": "gemma2-9b-it", "name": "Gemma2 9B IT"},
        {"id": "mixtral-8x7b-32768", "name": "Mixtral 8x7B 32K"},
        {"id": "compound-beta", "name": "Compound Beta (multi-step)"},
        {"id": "compound-beta-mini", "name": "Compound Beta Mini"},
        {"id": "llama3-70b-8192", "name": "Llama3 70B 8K"},
        {"id": "llama3-8b-8192", "name": "Llama3 8B 8K"},
    ]

    def __init__(self, config: dict):
        super().__init__(config)
        self.model = config.get("model", "llama-3.3-70b-versatile")
        self.timeout = config.get("timeout", 120)
        self.temperature = config.get("temperature", 0.7)
        self.max_output_tokens = config.get("max_output_tokens", 8192)
        self.max_tool_iterations = config.get("max_tool_iterations", 20)
        self.max_tools = config.get("max_tools", 0)
        self.notify_tool_use = config.get("notify_tool_use", True)

        self._client = None
        self._tool_adapter = GroqToolAdapter()
        self._valid_tool_names: set[str] = set()

        # Session history: session_id -> list of messages
        self._sessions: dict[str, list[dict]] = {}

    async def initialize(self) -> None:
        """Initialize the Groq client."""
        try:
            from groq import AsyncGroq
        except ImportError:
            logger.error(
                "groq package not installed — run: pip install groq"
            )
            return

        api_key = secrets_manager.get_plain("groq_api_key") or os.getenv("GROQ_API_KEY")
        if not api_key:
            logger.error("groq_api_key not set in vault — Groq runner disabled")
            return

        self._client = AsyncGroq(api_key=api_key, timeout=self.timeout)
        logger.info(
            "Groq runner initialized (model=%s, timeout=%ds)",
            self.model,
            self.timeout,
        )

    async def shutdown(self) -> None:
        """Cleanup resources."""
        await self._tool_adapter.shutdown()
        self._client = None
        self._sessions.clear()
        logger.info("Groq runner shut down")

    async def supports_tools(self) -> bool:
        """Groq supports native function calling on most models."""
        return True

    async def supports_vision(self) -> bool:
        """Vision not supported yet on Groq."""
        return False

    @property
    def available_models(self) -> list[tuple[str, str]]:
        """Return Groq model choices from registry."""
        from core.registry import get_models_registry

        registry = get_models_registry()
        if registry:
            registry.seed_if_empty("groq", self._DEFAULT_MODELS)
            models = registry.get_for_ui("groq")
            if models:
                return models
        return [(m["id"], m["name"]) for m in self._DEFAULT_MODELS]

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
        """Execute Groq API call with session, tool calling, and streaming support.

        Args:
            prompt: The full prompt to send
            session_id: Session ID for multi-turn conversations
            progress_callback: Optional async callback for progress messages
            error_callback: Optional async callback for error notifications
            tool_callback: Optional async callback for tool use notifications
            stream_callback: Optional async callback for streaming text
            agent_id: Agent identifier for MCP token and logging
            model: Per-agent model override
            no_tools: If True, skip MCP tools
        """
        if not self._client:
            msg = "Groq client not initialized (missing groq_api_key in vault?)"
            logger.error(msg)
            if error_callback:
                await error_callback("runner_error", msg)
            return RunnerResponse(text=msg, is_error=True)

        effective_model = model or self.model
        agent_label = agent_id or "default"

        logger.info(
            "[%s] Groq call: model=%s, prompt_len=%d",
            agent_label,
            effective_model,
            len(prompt),
        )

        try:
            # --- Session management ---
            if not session_id:
                session_id = f"groq-{agent_label}-{id(prompt)}"
            history = self._sessions.setdefault(session_id, [])

            # --- Tool setup ---
            unified_id = kwargs.get("unified_id")
            agent_max_tools = kwargs.get("max_tools")
            tools = None
            tool_capable = effective_model in _TOOL_CAPABLE_MODELS
            if not no_tools and agent_id and tool_capable:
                tools = await self._setup_tools(agent_id, unified_id, agent_max_tools)

            # Build system prompt
            system_prompt = kwargs.get("system_prompt", "")
            if tools:
                system_prompt = self._augment_system_prompt(system_prompt)

            # Build messages
            api_messages: list[dict] = []
            if system_prompt:
                api_messages.append({"role": "system", "content": system_prompt})
            api_messages.extend(history)
            api_prompt = self._sanitize_prompt(prompt) if tools else prompt
            api_messages.append({"role": "user", "content": api_prompt})

            # --- API call with tool loop ---
            total_input_tokens = 0
            total_output_tokens = 0
            iterations = 0

            while True:
                text, tool_calls, usage = await self._call_api(
                    model=effective_model,
                    messages=api_messages,
                    tools=tools,
                    stream_callback=stream_callback,
                )

                if usage:
                    total_input_tokens += usage.get("prompt_tokens", 0)
                    total_output_tokens += usage.get("completion_tokens", 0)

                if tool_calls and not no_tools:
                    iterations += 1
                    if iterations > self.max_tool_iterations:
                        msg = (
                            f"Max tool iterations ({self.max_tool_iterations}) reached."
                        )
                        logger.warning("[%s] %s", agent_label, msg)
                        return RunnerResponse(
                            text=msg,
                            session_id=session_id,
                            is_error=True,
                            raw={"model": effective_model, "runner": "groq"},
                        )

                    # Add assistant message with tool calls
                    api_messages.append(
                        {
                            "role": "assistant",
                            "content": text or "",
                            "tool_calls": tool_calls,
                        }
                    )

                    # Execute all tool calls
                    tool_results = await self._execute_tool_calls(
                        tool_calls, tool_callback, agent_label
                    )
                    api_messages.extend(tool_results)

                    # Don't stream intermediate iterations
                    stream_callback = None
                    continue

                break

            # Save to session history
            history.append({"role": "user", "content": prompt})
            history.append({"role": "assistant", "content": text or ""})
            # Keep last 20 turns to avoid huge contexts
            if len(history) > 40:
                self._sessions[session_id] = history[-40:]

            logger.info(
                "[%s] Groq done: in=%d out=%d iters=%d",
                agent_label,
                total_input_tokens,
                total_output_tokens,
                iterations,
            )

            return RunnerResponse(
                text=text or "",
                session_id=session_id,
                raw={
                    "model": effective_model,
                    "runner": "groq",
                    "tool_iterations": iterations,
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                },
            )

        except Exception as e:
            msg = f"Groq API error: {e}"
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
    ) -> tuple[str, list[dict] | None, dict | None]:
        """Call Groq API. Returns (text, tool_calls, usage_dict)."""
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_output_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        last_error = None
        for attempt in range(3):
            if attempt > 0:
                delay = 2 ** attempt
                logger.info("Groq retry %d after %ds", attempt, delay)
                await asyncio.sleep(delay)
            try:
                if stream_callback and not tools:
                    return await self._call_streaming(kwargs, stream_callback)
                else:
                    return await self._call_unary(kwargs)
            except Exception as e:
                last_error = e
                err_str = str(e).lower()
                is_transient = any(m in err_str for m in _TRANSIENT_ERRORS)
                if not is_transient or attempt >= 2:
                    raise
                logger.warning("Transient Groq error (attempt %d): %s", attempt + 1, e)

        raise last_error  # pragma: no cover

    async def _call_unary(self, kwargs: dict) -> tuple[str, list | None, dict | None]:
        """Non-streaming Groq API call."""
        response = await self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        text = choice.message.content or ""
        tool_calls = None
        if choice.message.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in choice.message.tool_calls
            ]
        usage = None
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
            }
        return text, tool_calls, usage

    async def _call_streaming(
        self, kwargs: dict, stream_callback
    ) -> tuple[str, None, dict | None]:
        """Streaming Groq API call."""
        kwargs["stream"] = True
        accumulated = ""
        async with await self._client.chat.completions.create(**kwargs) as stream:
            async for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    accumulated += delta.content
                    try:
                        await stream_callback(accumulated)
                    except Exception:
                        pass
        return accumulated, None, None

    async def _setup_tools(
        self,
        agent_id: str,
        unified_id: str | None = None,
        agent_max_tools: int | None = None,
    ) -> list[dict] | None:
        """Load MCP tools and convert to Groq format."""
        try:
            await self._tool_adapter.initialize(agent_id, unified_id=unified_id)
            effective_max = agent_max_tools or self.max_tools or None
            mcp_tools = await self._tool_adapter.list_tools(tool_budget=effective_max)
            if not mcp_tools:
                self._valid_tool_names = set()
                return None
            if effective_max and len(mcp_tools) > effective_max:
                mcp_tools = mcp_tools[:effective_max]
            groq_tools = self._tool_adapter.mcp_to_groq_tools(mcp_tools)
            self._valid_tool_names = {
                t["function"]["name"] for t in groq_tools
            }
            logger.info("[%s] Loaded %d MCP tools for Groq", agent_id, len(groq_tools))
            return groq_tools
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
        """Execute tool calls via ToolAdapter and return tool messages."""
        results = []
        for tc in tool_calls:
            func = tc.get("function", {})
            name = func.get("name", "")
            tool_call_id = tc.get("id", "call_0")

            # Parse arguments (Groq returns JSON string)
            raw_args = func.get("arguments", "{}")
            if isinstance(raw_args, str):
                try:
                    arguments = json.loads(raw_args)
                except json.JSONDecodeError:
                    arguments = {}
            else:
                arguments = raw_args or {}

            # Reject hallucinated tool names
            if self._valid_tool_names and name not in self._valid_tool_names:
                logger.warning(
                    "[%s] Rejected unknown tool '%s'", agent_label, name
                )
                results.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": (
                            f"Error: function '{name}' is not available. "
                            "Use only the provided function definitions."
                        ),
                    }
                )
                continue

            logger.info("[%s] Tool call: %s args=%s", agent_label, name, arguments)

            if tool_callback:
                try:
                    await tool_callback(name, arguments)
                except Exception as e:
                    logger.debug("tool_callback error: %s", e)

            content = await self._tool_adapter.call_tool(name, arguments)
            results.append(
                self._tool_adapter.format_tool_result(content, tool_call_id=tool_call_id)
            )

        return results

    @staticmethod
    def _augment_system_prompt(system_prompt: str) -> str:
        """Add function calling instructions when tools are available."""
        tool_instruction = (
            "\n\n[CRITICAL - Function Calling Protocol]\n"
            "You have structured function calling tools available.\n"
            "ALL services (Odoo, HomeAssistant, Gmail, GitHub, etc.) are available "
            "as structured function calls. NEVER write tool names as text. "
            "Use the function declarations provided.\n"
            "When you need Odoo data: call odoo_search_read, odoo_create, etc. directly.\n"
            "Always fill in the required arguments from the function schema."
        )
        return (
            (system_prompt + tool_instruction)
            if system_prompt
            else tool_instruction.strip()
        )

    @staticmethod
    def _sanitize_prompt(prompt: str) -> str:
        """Clean MCP references from prompt for structured function calling."""
        prompt = re.sub(r"\[MCP Permissions:[^\]]*\]", "", prompt)
        prompt = re.sub(r"\[Built-in Tools:[^\]]*\]", "", prompt)
        prompt = re.sub(r"mcp__[\w-]+__\w+(?:\s+with\s+[^\n]*)?", "", prompt)
        prompt = re.sub(r"\n{3,}", "\n\n", prompt)
        return prompt
