"""GridBear LLM Adapter for LiveKit Agent.

Routes LLM requests through GridBear's MessageProcessor via HTTP bridge,
giving the voice agent access to Claude + MCP tools + memory.
"""

import asyncio
import logging
import os
from typing import Any

import aiohttp
import psycopg
from livekit.agents import llm
from livekit.agents.types import (
    DEFAULT_API_CONNECT_OPTIONS,
    NOT_GIVEN,
    APIConnectOptions,
    NotGivenOr,
)

logger = logging.getLogger("livekit-worker.gridbear-llm")


class GridBearLLMStream(llm.LLMStream):
    """Stream that sends a single complete response from GridBear."""

    def __init__(
        self,
        owner: "GridBearLLM",
        *,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool],
        conn_options: APIConnectOptions,
        response_text: str,
    ) -> None:
        super().__init__(
            owner, chat_ctx=chat_ctx, tools=tools, conn_options=conn_options
        )
        self._response_text = response_text

    async def _run(self) -> None:
        self._event_ch.send_nowait(
            llm.ChatChunk(
                id="gridbear-response",
                delta=llm.ChoiceDelta(
                    role="assistant",
                    content=self._response_text,
                ),
                usage=llm.CompletionUsage(
                    completion_tokens=0,
                    prompt_tokens=0,
                    total_tokens=0,
                ),
            )
        )


class GridBearLLM(llm.LLM):
    """LLM adapter that proxies requests through GridBear's message processor."""

    def __init__(self, *, port: int, room_name: str = "") -> None:
        super().__init__()
        self._port = port
        self._room_name = room_name
        self._session: aiohttp.ClientSession | None = None

    @property
    def model(self) -> str:
        return "gridbear-proxy"

    @property
    def provider(self) -> str:
        return "gridbear"

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def chat(
        self,
        *,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool] | None = None,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
        parallel_tool_calls: NotGivenOr[bool] = NOT_GIVEN,
        tool_choice: NotGivenOr[llm.ToolChoice] = NOT_GIVEN,
        extra_kwargs: NotGivenOr[dict[str, Any]] = NOT_GIVEN,
    ) -> llm.LLMStream:
        # Extract the last user message
        text = ""
        for msg in reversed(chat_ctx.messages()):
            if msg.role == "user":
                text = msg.text_content or ""
                break

        if not text:
            logger.warning("No user message found in chat context")
            return GridBearLLMStream(
                self,
                chat_ctx=chat_ctx,
                tools=tools or [],
                conn_options=conn_options,
                response_text="Non ho capito, puoi ripetere?",
            )

        return _GridBearBridgeStream(
            self,
            chat_ctx=chat_ctx,
            tools=tools or [],
            conn_options=conn_options,
            text=text,
            port=self._port,
            room_name=self._room_name,
        )

    async def aclose(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


class _GridBearBridgeStream(llm.LLMStream):
    """Stream that calls the GridBear bridge and returns the response."""

    def __init__(
        self,
        owner: GridBearLLM,
        *,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool],
        conn_options: APIConnectOptions,
        text: str,
        port: int,
        room_name: str,
    ) -> None:
        super().__init__(
            owner, chat_ctx=chat_ctx, tools=tools, conn_options=conn_options
        )
        self._text = text
        self._port = port
        self._room_name = room_name

    def _get_caller_from_session(self) -> tuple[str, str, str | None]:
        """Get caller's user_id, user_name, and caller_identity from session DB.

        Returns:
            (user_id, user_name, caller_identity) where caller_identity is
            "platform:username" (e.g. "telegram:johndoe") or None.
        """
        dsn = os.environ.get("DATABASE_URL", "")
        if not dsn:
            logger.warning("DATABASE_URL not set, cannot look up caller")
            return "livekit-user", "Voice User", None
        try:
            with psycopg.connect(dsn) as conn:
                row = conn.execute(
                    "SELECT user_id, user_name, caller_identity "
                    "FROM app.livekit_sessions "
                    "WHERE room_name = %s AND ended_at IS NULL "
                    "ORDER BY created_at DESC LIMIT 1",
                    (self._room_name,),
                ).fetchone()
                if row:
                    return (
                        row[0] or "livekit-user",
                        row[1] or "Voice User",
                        row[2],
                    )
        except Exception as e:
            logger.warning(f"Failed to look up caller from session DB: {e}")
        return "livekit-user", "Voice User", None

    async def _run(self) -> None:
        url = f"http://localhost:{self._port}/api/livekit-agent/llm-bridge"

        # Look up real caller identity from session DB
        caller_id, caller_name, caller_identity = self._get_caller_from_session()

        payload = {
            "text": self._text,
            "user_id": caller_id,
            "user_name": caller_name,
            "room_name": self._room_name,
            "caller_identity": caller_identity,
        }

        logger.info(f"Sending to GridBear bridge: {self._text[:80]}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=payload, timeout=aiohttp.ClientTimeout(total=120)
                ) as resp:
                    data = await resp.json()

            inner = data.get("data", {}) or {}
            response_text = inner.get("text", "")
            if not data.get("ok", True):
                logger.error(f"GridBear bridge error: {data.get('error')}")
                response_text = response_text or "Mi dispiace, c'è stato un errore."

            if not response_text:
                response_text = "Non ho una risposta al momento."

            logger.info(f"GridBear response: {response_text[:80]}")

        except asyncio.TimeoutError:
            logger.error("GridBear bridge request timed out")
            response_text = "Mi dispiace, ci sto mettendo troppo tempo. Riprova."
        except Exception as e:
            logger.error(f"GridBear bridge request failed: {e}")
            response_text = "Mi dispiace, c'è stato un problema di connessione."

        self._event_ch.send_nowait(
            llm.ChatChunk(
                id="gridbear-response",
                delta=llm.ChoiceDelta(
                    role="assistant",
                    content=response_text,
                ),
                usage=llm.CompletionUsage(
                    completion_tokens=0,
                    prompt_tokens=0,
                    total_tokens=0,
                ),
            )
        )
