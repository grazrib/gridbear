"""LiveKit Agent MCP Server.

Provides tools for starting and managing voice calls via LiveKit.
Runs as a standalone stdio subprocess — uses psycopg directly (no app registry).
"""

import asyncio
import os
import secrets
import time
from datetime import datetime, timedelta

import psycopg

# LiveKit SDK
from livekit import api

# MCP SDK
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from psycopg.rows import dict_row

# Configuration from environment
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY", "")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "")
LIVEKIT_WS_URL = os.getenv("LIVEKIT_WS_URL", "")
AGENT_NAME = os.getenv("AGENT_NAME", "Peggy")
STT_LANGUAGE = os.getenv("STT_LANGUAGE", "it")
TTS_VOICE = os.getenv("TTS_VOICE", "nova")
BASE_URL = os.getenv("BASE_URL", "") or os.getenv("GRIDBEAR_BASE_URL", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")


def _get_conn():
    """Get a psycopg connection with dict rows and autocommit."""
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not configured")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=True)


def _save_session(room_name: str, data: dict):
    """Save session to database."""
    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO app.livekit_sessions
            (room_name, user_id, user_name, user_token, agent_token, ws_url,
             cleanup_token, caller_identity, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (room_name) DO UPDATE SET
                user_id = EXCLUDED.user_id,
                user_name = EXCLUDED.user_name,
                user_token = EXCLUDED.user_token,
                agent_token = EXCLUDED.agent_token,
                ws_url = EXCLUDED.ws_url,
                cleanup_token = EXCLUDED.cleanup_token,
                caller_identity = EXCLUDED.caller_identity
            """,
            (
                room_name,
                data["user_id"],
                data.get("user_name", ""),
                data["user_token"],
                data["agent_token"],
                data["ws_url"],
                data.get("cleanup_token", ""),
                data.get("caller_identity"),
                data["created_at"],
            ),
        )
        row = conn.execute(
            "SELECT room_name FROM app.livekit_sessions WHERE room_name = %s",
            (room_name,),
        ).fetchone()
        if not row:
            raise RuntimeError(f"Session {room_name} not found after save")


def _get_session(room_name: str) -> dict | None:
    """Get session from database."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM app.livekit_sessions WHERE room_name = %s",
            (room_name,),
        ).fetchone()
    return row


def _get_session_by_user(user_id: str) -> dict | None:
    """Get session by user_id."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM app.livekit_sessions WHERE user_id = %s",
            (user_id,),
        ).fetchone()
    return row


def _delete_session(room_name: str):
    """Delete session from database."""
    with _get_conn() as conn:
        conn.execute(
            "DELETE FROM app.livekit_sessions WHERE room_name = %s",
            (room_name,),
        )


def _get_all_sessions() -> list[dict]:
    """Get all sessions."""
    with _get_conn() as conn:
        rows = conn.execute("SELECT * FROM app.livekit_sessions").fetchall()
    return rows


server = Server("livekit-agent")


def _create_token(identity: str, name: str, room: str, is_admin: bool = False) -> str:
    """Create a LiveKit access token."""
    token = (
        api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        .with_identity(identity)
        .with_name(name)
        .with_ttl(timedelta(hours=1))
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room,
                room_admin=is_admin,
            )
        )
    )
    return token.to_jwt()


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return [
        Tool(
            name="start_voice_call",
            description=(
                "Avvia una chiamata vocale real-time con l'utente corrente. "
                "Restituisce l'URL della room LiveKit. "
                "IMPORTANTE: Mostra l'URL esattamente come restituito, senza formattazione markdown, "
                "senza grassetto, senza parentesi quadre. L'utente deve poterlo copiare e incollare."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "ID dell'utente (es: telegram_123456, discord_username)",
                    },
                    "user_name": {
                        "type": "string",
                        "description": "Nome visualizzato dell'utente nella chiamata",
                    },
                    "caller_identity": {
                        "type": "string",
                        "description": (
                            "Identità del chiamante nel formato platform:username "
                            "(es: telegram:johndoe, discord:janedoe). "
                            "Necessario per i permessi MCP durante la chiamata."
                        ),
                    },
                },
                "required": ["user_id"],
            },
        ),
        Tool(
            name="end_voice_call",
            description="Termina una chiamata vocale attiva.",
            inputSchema={
                "type": "object",
                "properties": {
                    "room_name": {
                        "type": "string",
                        "description": "Nome della room da terminare",
                    },
                },
                "required": ["room_name"],
            },
        ),
        Tool(
            name="list_active_calls",
            description="Elenca tutte le chiamate vocali attive.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="get_call_link",
            description="Ottiene il link per una chiamata esistente.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "ID dell'utente per cui cercare la chiamata",
                    },
                },
                "required": ["user_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Execute a tool."""
    if not LIVEKIT_API_KEY or not LIVEKIT_API_SECRET or not LIVEKIT_WS_URL:
        return [
            TextContent(
                type="text",
                text="Errore: LiveKit non configurato. Mancano API_KEY, API_SECRET o WS_URL.",
            )
        ]

    if name == "start_voice_call":
        return await _start_voice_call(arguments)
    elif name == "end_voice_call":
        return await _end_voice_call(arguments)
    elif name == "list_active_calls":
        return await _list_active_calls(arguments)
    elif name == "get_call_link":
        return await _get_call_link(arguments)
    else:
        return [TextContent(type="text", text=f"Tool sconosciuto: {name}")]


async def _start_voice_call(args: dict) -> list[TextContent]:
    """Start a voice call."""
    user_id = args.get("user_id", "")
    user_name = args.get("user_name", user_id)
    caller_identity = args.get("caller_identity")

    if not user_id:
        return [TextContent(type="text", text="Errore: user_id richiesto")]

    # Check for existing call — reuse if token still valid (< 50 min)
    existing = _get_session_by_user(user_id)
    if existing:
        try:
            created = datetime.fromisoformat(str(existing["created_at"]))
            age_minutes = (datetime.now() - created).total_seconds() / 60
        except Exception:
            age_minutes = 999
        if age_minutes < 50:
            call_url = f"{BASE_URL}/plugin/livekit-agent/call/{existing['room_name']}"
            return [TextContent(type="text", text=call_url)]
        # Token expired — clean up old session
        _delete_session(existing["room_name"])

    # Create new room
    room_name = f"call-{user_id.replace('@', '').replace(' ', '-')}-{int(time.time())}"

    # Generate tokens
    user_token = _create_token(user_id, user_name, room_name, is_admin=False)
    agent_token = _create_token(
        f"agent-{AGENT_NAME.lower()}", AGENT_NAME, room_name, is_admin=True
    )

    # Store session in PostgreSQL
    cleanup_token = secrets.token_urlsafe(16)
    try:
        _save_session(
            room_name,
            {
                "user_id": user_id,
                "user_name": user_name,
                "user_token": user_token,
                "agent_token": agent_token,
                "ws_url": LIVEKIT_WS_URL,
                "cleanup_token": cleanup_token,
                "caller_identity": caller_identity,
                "created_at": datetime.now().isoformat(),
            },
        )
    except Exception as e:
        return [TextContent(type="text", text=f"Errore nel salvare la sessione: {e}")]

    # Agent joins automatically via auto-dispatch when user connects to the room

    # Simple URL - admin will look up token from database
    call_url = f"{BASE_URL}/plugin/livekit-agent/call/{room_name}"

    return [TextContent(type="text", text=call_url)]


async def _end_voice_call(args: dict) -> list[TextContent]:
    """End a voice call."""
    room_name = args.get("room_name", "")

    if not room_name:
        return [TextContent(type="text", text="Errore: room_name richiesto")]

    session = _get_session(room_name)
    if not session:
        return [TextContent(type="text", text=f"Chiamata non trovata: {room_name}")]

    # Try to delete room via LiveKit API
    try:
        room_service = api.RoomService(
            LIVEKIT_WS_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET
        )
        await room_service.delete_room(api.DeleteRoomRequest(room=room_name))
    except Exception:
        pass  # Room might not exist on server

    # Remove from database
    _delete_session(room_name)

    return [TextContent(type="text", text=f"Chiamata terminata: {room_name}")]


async def _list_active_calls(args: dict) -> list[TextContent]:
    """List active calls."""
    sessions = _get_all_sessions()
    if not sessions:
        return [TextContent(type="text", text="Nessuna chiamata attiva.")]

    lines = ["Chiamate attive:\n"]
    for session in sessions:
        lines.append(
            f"- Room: {session['room_name']}\n"
            f"  Utente: {session.get('user_name') or session.get('user_id')}\n"
            f"  Creata: {session.get('created_at', 'N/A')}\n"
        )

    return [TextContent(type="text", text="\n".join(lines))]


async def _get_call_link(args: dict) -> list[TextContent]:
    """Get call link for a user."""
    user_id = args.get("user_id", "")

    if not user_id:
        return [TextContent(type="text", text="Errore: user_id richiesto")]

    session = _get_session_by_user(user_id)
    if session:
        call_url = f"{BASE_URL}/plugin/livekit-agent/call/{session['room_name']}"
        return [TextContent(type="text", text=call_url)]

    return [TextContent(type="text", text=f"Nessuna chiamata attiva per {user_id}")]


async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream, server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
