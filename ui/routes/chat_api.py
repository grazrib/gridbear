"""Chat history REST API for user portal (PostgreSQL).

Provides conversation management and message persistence for WebChat.
Storage: PostgreSQL chat.webchat_conversations / chat.webchat_messages.
"""

import json
import os
import re
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from config.logging_config import logger
from core.api_schemas import ApiResponse, api_error, api_ok
from core.encryption import decrypt, encrypt, is_encrypted
from ui.routes.auth import require_user

router = APIRouter(prefix="/me/chat/api", tags=["chat-api"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ATTACHMENTS_DIR = BASE_DIR / "data" / "attachments"

# Max upload: 20MB per file, images + common doc types
MAX_UPLOAD_SIZE = 20 * 1024 * 1024
ALLOWED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".bmp",
    ".svg",
    ".pdf",
    ".txt",
    ".csv",
    ".json",
    ".xml",
    ".md",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".mp3",
    ".wav",
    ".m4a",
    ".ogg",
    ".flac",
    ".webm",
    ".mp4",
}

MIGRATION_NAME = "004_apps_webchat"
MIGRATION_SQL = BASE_DIR / "scripts" / "migrations" / f"{MIGRATION_NAME}.sql"

_db = None
_initialized = False


def _ensure_db():
    """Initialize PG database reference and apply migration if needed."""
    global _db, _initialized
    if _initialized:
        return

    from core.registry import get_database

    _db = get_database()
    if _db is None:
        raise RuntimeError("PostgreSQL database not available (chat API requires it)")

    with _db.acquire_sync() as conn:
        row = conn.execute(
            "SELECT 1 FROM public._migrations WHERE name = %s",
            (MIGRATION_NAME,),
        ).fetchone()
        if not row:
            sql = MIGRATION_SQL.read_text()
            conn.execute(sql)
            conn.execute(
                "INSERT INTO public._migrations (name) VALUES (%s)",
                (MIGRATION_NAME,),
            )
            conn.commit()
            logger.info(f"Applied {MIGRATION_NAME} migration (chat_api)")
        else:
            conn.rollback()

    # Ensure context_prompt column exists (idempotent)
    with _db.acquire_sync() as conn:
        conn.execute(
            "ALTER TABLE chat.webchat_conversations "
            "ADD COLUMN IF NOT EXISTS context_prompt TEXT"
        )
        # Shared conversations schema
        conn.execute(
            "ALTER TABLE chat.webchat_conversations "
            "ADD COLUMN IF NOT EXISTS type TEXT DEFAULT 'private'"
        )
        conn.execute(
            "ALTER TABLE chat.webchat_messages ADD COLUMN IF NOT EXISTS sender_id TEXT"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat.webchat_participants (
                conversation_id TEXT NOT NULL
                    REFERENCES chat.webchat_conversations(id) ON DELETE CASCADE,
                unified_id TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'member',
                joined_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (conversation_id, unified_id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_webchat_participants_uid
            ON chat.webchat_participants(unified_id)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat.webchat_invites (
                token TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL
                    REFERENCES chat.webchat_conversations(id) ON DELETE CASCADE,
                created_by TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMPTZ NOT NULL,
                max_uses INTEGER DEFAULT 0,
                use_count INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_webchat_invites_conv
            ON chat.webchat_invites(conversation_id)
        """)
        # Backfill: create owner participant for existing conversations
        conn.execute("""
            INSERT INTO chat.webchat_participants (conversation_id, unified_id, role)
            SELECT id, unified_id, 'owner'
            FROM chat.webchat_conversations
            WHERE id NOT IN (
                SELECT conversation_id FROM chat.webchat_participants
            )
            ON CONFLICT DO NOTHING
        """)
        conn.commit()

    _initialized = True


def _uid(user: dict) -> str:
    return user["username"]


def _serialize_row(row: dict) -> dict:
    """Convert datetime values to ISO strings for JSON serialization."""
    return {k: v.isoformat() if hasattr(v, "isoformat") else v for k, v in row.items()}


# --- Public helpers (used by ws_chat) ---


def save_message(
    conversation_id: str,
    role: str,
    content: str,
    metadata: dict | None = None,
    sender_id: str | None = None,
):
    """Save a message and update conversation timestamp. Auto-title if empty."""
    _ensure_db()
    encrypted_content = encrypt(content)
    with _db.acquire_sync() as conn:
        conn.execute(
            """INSERT INTO chat.webchat_messages
               (conversation_id, role, content, metadata_json, sender_id)
               VALUES (%s, %s, %s, %s, %s)""",
            (
                conversation_id,
                role,
                encrypted_content,
                json.dumps(metadata) if metadata else None,
                sender_id,
            ),
        )
        conn.execute(
            "UPDATE chat.webchat_conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (conversation_id,),
        )
        # Auto-title: set title from first user message
        if role == "user":
            row = conn.execute(
                "SELECT title FROM chat.webchat_conversations WHERE id = %s",
                (conversation_id,),
            ).fetchone()
            if row and not row["title"]:
                title = content[:80].strip()
                if len(content) > 80:
                    title += "..."
                conn.execute(
                    "UPDATE chat.webchat_conversations SET title = %s WHERE id = %s",
                    (title, conversation_id),
                )
        conn.commit()


def get_conversation_title(conversation_id: str) -> str:
    """Get current title of a conversation."""
    _ensure_db()
    with _db.acquire_sync() as conn:
        row = conn.execute(
            "SELECT title FROM chat.webchat_conversations WHERE id = %s",
            (conversation_id,),
        ).fetchone()
    return row["title"] if row else ""


def validate_conversation_ownership(conversation_id: str, unified_id: str) -> bool:
    """Check that a conversation belongs to the given user (legacy — private only)."""
    _ensure_db()
    with _db.acquire_sync() as conn:
        row = conn.execute(
            "SELECT 1 FROM chat.webchat_conversations WHERE id = %s AND unified_id = %s",
            (conversation_id, unified_id),
        ).fetchone()
    return row is not None


def validate_conversation_access(conversation_id: str, uid: str) -> str | None:
    """Check if user is a participant (owner or member). Returns role or None."""
    _ensure_db()
    with _db.acquire_sync() as conn:
        row = conn.execute(
            "SELECT role FROM chat.webchat_participants "
            "WHERE conversation_id = %s AND unified_id = %s",
            (conversation_id, uid),
        ).fetchone()
        return row["role"] if row else None


def is_conversation_owner(conversation_id: str, uid: str) -> bool:
    """Check if user is the owner of a conversation."""
    return validate_conversation_access(conversation_id, uid) == "owner"


def list_conversation_participants(conversation_id: str) -> list[str]:
    """Return list of participant unified_ids for a conversation."""
    _ensure_db()
    with _db.acquire_sync() as conn:
        rows = conn.execute(
            "SELECT unified_id FROM chat.webchat_participants "
            "WHERE conversation_id = %s",
            (conversation_id,),
        ).fetchall()
    return [r["unified_id"] for r in rows]


# --- REST endpoints ---


@router.get(
    "/conversations",
    response_model=ApiResponse[dict],
    response_model_exclude_none=True,
)
async def list_conversations(request: Request, user: dict = Depends(require_user)):
    _ensure_db()
    agent = request.query_params.get("agent", "")
    uid = _uid(user)
    with _db.acquire_sync() as conn:
        if agent:
            cur = conn.execute(
                """SELECT c.id, c.agent_name, c.title, c.created_at,
                          c.updated_at, c.type, c.context_prompt
                   FROM chat.webchat_conversations c
                   JOIN chat.webchat_participants p
                        ON c.id = p.conversation_id
                   WHERE p.unified_id = %s AND c.agent_name = %s
                   ORDER BY c.updated_at DESC""",
                (uid, agent),
            )
        else:
            cur = conn.execute(
                """SELECT c.id, c.agent_name, c.title, c.created_at,
                          c.updated_at, c.type, c.context_prompt
                   FROM chat.webchat_conversations c
                   JOIN chat.webchat_participants p
                        ON c.id = p.conversation_id
                   WHERE p.unified_id = %s
                   ORDER BY c.updated_at DESC""",
                (uid,),
            )
        rows = [_serialize_row(dict(r)) for r in cur.fetchall()]
    return api_ok(data={"conversations": rows})


@router.post(
    "/conversations",
    response_model=ApiResponse[dict],
    response_model_exclude_none=True,
)
async def create_conversation(request: Request, user: dict = Depends(require_user)):
    try:
        body = await request.json()
    except Exception:
        return api_error(400, "Invalid JSON", "validation_error")

    agent_name = body.get("agent_name", "")
    uid = _uid(user)

    # Validate agent access
    if agent_name and not user.get("is_superadmin"):
        from ui.routes.me import _get_allowed_users
        from ui.routes.ws_chat import _load_agent_yaml

        agent_cfg = _load_agent_yaml(agent_name)
        if agent_cfg:
            allowed = _get_allowed_users(agent_cfg)
            if not allowed or uid.lower() not in allowed:
                return api_error(403, "Access denied to this agent", "forbidden")

    conv_id = str(uuid.uuid4())

    _ensure_db()
    with _db.acquire_sync() as conn:
        conn.execute(
            """INSERT INTO chat.webchat_conversations (id, unified_id, agent_name)
               VALUES (%s, %s, %s)""",
            (conv_id, uid, agent_name),
        )
        # Create owner participant
        conn.execute(
            """INSERT INTO chat.webchat_participants
               (conversation_id, unified_id, role)
               VALUES (%s, %s, 'owner')""",
            (conv_id, uid),
        )
        conn.commit()
        row = conn.execute(
            """SELECT id, agent_name, title, created_at, updated_at, type
               FROM chat.webchat_conversations WHERE id = %s""",
            (conv_id,),
        ).fetchone()
    return api_ok(data={"conversation": _serialize_row(dict(row))})


@router.get(
    "/conversations/{conv_id}/messages",
    response_model=ApiResponse[dict],
    response_model_exclude_none=True,
)
async def get_messages(
    request: Request, conv_id: str, user: dict = Depends(require_user)
):
    _ensure_db()
    uid = _uid(user)
    with _db.acquire_sync() as conn:
        # Ownership check
        row = conn.execute(
            "SELECT 1 FROM chat.webchat_conversations WHERE id = %s AND unified_id = %s",
            (conv_id, uid),
        ).fetchone()
        if not row:
            return api_error(404, "Not found", "not_found")

        limit = int(request.query_params.get("limit", "200"))
        offset = int(request.query_params.get("offset", "0"))

        cur = conn.execute(
            """SELECT id, role, content, metadata_json, created_at
               FROM chat.webchat_messages
               WHERE conversation_id = %s
               ORDER BY created_at ASC
               LIMIT %s OFFSET %s""",
            (conv_id, limit, offset),
        )
        rows = []
        for r in cur.fetchall():
            msg = _serialize_row(dict(r))
            # Decrypt content (handles both encrypted and pre-migration plaintext)
            raw = msg.get("content", "")
            msg["content"] = decrypt(raw) if is_encrypted(raw) else raw
            if msg["metadata_json"]:
                msg["metadata"] = json.loads(msg["metadata_json"])
            del msg["metadata_json"]
            rows.append(msg)

    return api_ok(data={"messages": rows})


@router.post(
    "/conversations/{conv_id}/rename",
    response_model=ApiResponse[dict],
    response_model_exclude_none=True,
)
async def rename_conversation(
    request: Request, conv_id: str, user: dict = Depends(require_user)
):
    try:
        body = await request.json()
    except Exception:
        return api_error(400, "Invalid JSON", "validation_error")

    title = (body.get("title") or "").strip()
    if not title:
        return api_error(400, "Title required", "validation_error")

    _ensure_db()
    uid = _uid(user)
    with _db.acquire_sync() as conn:
        row = conn.execute(
            "SELECT 1 FROM chat.webchat_conversations WHERE id = %s AND unified_id = %s",
            (conv_id, uid),
        ).fetchone()
        if not row:
            return api_error(404, "Not found", "not_found")

        conn.execute(
            "UPDATE chat.webchat_conversations SET title = %s WHERE id = %s",
            (title, conv_id),
        )
        conn.commit()
    return api_ok(data={"title": title})


@router.delete(
    "/conversations/{conv_id}",
    response_model=ApiResponse,
    response_model_exclude_none=True,
)
async def delete_conversation(
    request: Request, conv_id: str, user: dict = Depends(require_user)
):
    _ensure_db()
    uid = _uid(user)
    with _db.acquire_sync() as conn:
        row = conn.execute(
            "SELECT 1 FROM chat.webchat_conversations WHERE id = %s AND unified_id = %s",
            (conv_id, uid),
        ).fetchone()
        if not row:
            return api_error(404, "Not found", "not_found")

        conn.execute(
            "DELETE FROM chat.webchat_conversations WHERE id = %s",
            (conv_id,),
        )
        conn.commit()
    return api_ok()


# --- Conversation context ---


@router.get(
    "/conversations/{conv_id}/context",
    response_model=ApiResponse[dict],
    response_model_exclude_none=True,
)
async def get_context(
    request: Request, conv_id: str, user: dict = Depends(require_user)
):
    """Get conversation context prompt."""
    _ensure_db()
    uid = _uid(user)
    with _db.acquire_sync() as conn:
        row = conn.execute(
            "SELECT context_prompt FROM chat.webchat_conversations "
            "WHERE id = %s AND unified_id = %s",
            (conv_id, uid),
        ).fetchone()
        if not row:
            return api_error(404, "Not found", "not_found")
    return api_ok(data={"context_prompt": row["context_prompt"]})


@router.post(
    "/conversations/{conv_id}/context",
    response_model=ApiResponse[dict],
    response_model_exclude_none=True,
)
async def set_context(
    request: Request, conv_id: str, user: dict = Depends(require_user)
):
    """Set or update conversation context prompt."""
    _ensure_db()
    uid = _uid(user)
    body = await request.json()
    context_prompt = body.get("context_prompt", "")

    # Validate length
    if isinstance(context_prompt, str) and len(context_prompt) > 2000:
        return api_error(
            422, "Context prompt too long (max 2000 characters)", "validation_error"
        )

    # Normalize empty → NULL
    context_prompt = context_prompt.strip() if context_prompt else None
    context_prompt = context_prompt or None

    with _db.acquire_sync() as conn:
        row = conn.execute(
            "SELECT 1 FROM chat.webchat_conversations "
            "WHERE id = %s AND unified_id = %s",
            (conv_id, uid),
        ).fetchone()
        if not row:
            return api_error(404, "Not found", "not_found")

        conn.execute(
            "UPDATE chat.webchat_conversations SET context_prompt = %s WHERE id = %s",
            (context_prompt, conv_id),
        )
        conn.commit()
    return api_ok(data={"context_prompt": context_prompt})


# --- Participants ---


@router.get(
    "/conversations/{conv_id}/participants",
    response_model=ApiResponse[dict],
    response_model_exclude_none=True,
)
async def list_participants(
    request: Request, conv_id: str, user: dict = Depends(require_user)
):
    """List participants of a conversation."""
    _ensure_db()
    uid = _uid(user)
    if not validate_conversation_access(conv_id, uid):
        return api_error(404, "Not found", "not_found")
    with _db.acquire_sync() as conn:
        rows = conn.execute(
            """SELECT p.unified_id, p.role, p.joined_at, u.display_name
               FROM chat.webchat_participants p
               LEFT JOIN app.users u ON u.username = p.unified_id
               WHERE p.conversation_id = %s
               ORDER BY p.joined_at""",
            (conv_id,),
        ).fetchall()
    participants = [
        {
            "uid": r["unified_id"],
            "role": r["role"],
            "display_name": r["display_name"] or r["unified_id"],
            "joined_at": r["joined_at"].isoformat() if r["joined_at"] else None,
        }
        for r in rows
    ]
    return api_ok(data={"participants": participants})


@router.post(
    "/conversations/{conv_id}/invite",
    response_model=ApiResponse[dict],
    response_model_exclude_none=True,
)
async def invite_user(
    request: Request, conv_id: str, user: dict = Depends(require_user)
):
    """Invite a registered user to a conversation. Owner only."""
    _ensure_db()
    uid = _uid(user)
    if not is_conversation_owner(conv_id, uid):
        return api_error(403, "Only the owner can invite", "forbidden")

    body = await request.json()
    target = body.get("username", "").strip().lower()
    if not target:
        return api_error(400, "username required", "validation_error")
    if target == uid:
        return api_error(400, "Cannot invite yourself", "validation_error")

    # Check target user exists
    from ui.auth.database import AuthDatabase

    auth_db = AuthDatabase()
    target_user = auth_db.get_user_by_username(target)
    if not target_user:
        return api_error(404, f"User '{target}' not found", "not_found")

    # Check not already participant
    if validate_conversation_access(conv_id, target):
        return api_error(400, "User already in conversation", "validation_error")

    with _db.acquire_sync() as conn:
        # Convert private → shared on first invite
        conv = conn.execute(
            "SELECT type FROM chat.webchat_conversations WHERE id = %s",
            (conv_id,),
        ).fetchone()
        if conv and conv["type"] == "private":
            conn.execute(
                "UPDATE chat.webchat_conversations SET type = 'shared' WHERE id = %s",
                (conv_id,),
            )

        # Add participant
        conn.execute(
            """INSERT INTO chat.webchat_participants
               (conversation_id, unified_id, role)
               VALUES (%s, %s, 'member')
               ON CONFLICT DO NOTHING""",
            (conv_id, target),
        )
        conn.commit()

    # Notify via WebSocket
    from ui.routes.ws_chat import push_to_webchat

    await push_to_webchat(
        target,
        {
            "type": "conversation_invited",
            "conversation_id": conv_id,
        },
    )
    return api_ok(data={"invited": target})


@router.post(
    "/conversations/{conv_id}/invite-link",
    response_model=ApiResponse[dict],
    response_model_exclude_none=True,
)
async def create_invite_link(
    request: Request, conv_id: str, user: dict = Depends(require_user)
):
    """Generate a shareable invite link. Owner only."""
    import secrets as stdlib_secrets

    _ensure_db()
    uid = _uid(user)
    if not is_conversation_owner(conv_id, uid):
        return api_error(403, "Only the owner can create invite links", "forbidden")

    body = await request.json()
    expires_hours = body.get("expires_hours", 72)
    max_uses = body.get("max_uses", 0)

    token = stdlib_secrets.token_urlsafe(32)
    with _db.acquire_sync() as conn:
        conn.execute(
            """INSERT INTO chat.webchat_invites
               (token, conversation_id, created_by, expires_at, max_uses)
               VALUES (%s, %s, %s, NOW() + INTERVAL '%s hours', %s)""",
            (token, conv_id, uid, expires_hours, max_uses),
        )
        # Convert to shared if private
        conn.execute(
            "UPDATE chat.webchat_conversations "
            "SET type = 'shared' WHERE id = %s AND type = 'private'",
            (conv_id,),
        )
        conn.commit()

    return api_ok(data={"url": f"/me/chat/join/{token}", "token": token})


@router.post(
    "/conversations/{conv_id}/leave",
    response_model=ApiResponse,
    response_model_exclude_none=True,
)
async def leave_conversation(
    request: Request, conv_id: str, user: dict = Depends(require_user)
):
    """Leave a shared conversation. Owner must transfer first."""
    _ensure_db()
    uid = _uid(user)
    role = validate_conversation_access(conv_id, uid)
    if not role:
        return api_error(404, "Not found", "not_found")
    if role == "owner":
        return api_error(
            400,
            "Owner must transfer ownership before leaving",
            "validation_error",
        )

    with _db.acquire_sync() as conn:
        conn.execute(
            "DELETE FROM chat.webchat_participants "
            "WHERE conversation_id = %s AND unified_id = %s",
            (conv_id, uid),
        )
        conn.commit()
    return api_ok()


@router.post(
    "/conversations/{conv_id}/transfer-ownership",
    response_model=ApiResponse,
    response_model_exclude_none=True,
)
async def transfer_ownership(
    request: Request, conv_id: str, user: dict = Depends(require_user)
):
    """Transfer conversation ownership to another participant. Owner only."""
    _ensure_db()
    uid = _uid(user)
    if not is_conversation_owner(conv_id, uid):
        return api_error(403, "Only the owner can transfer", "forbidden")

    body = await request.json()
    new_owner = body.get("new_owner", "").strip().lower()
    if not new_owner or new_owner == uid:
        return api_error(400, "Invalid new_owner", "validation_error")

    if not validate_conversation_access(conv_id, new_owner):
        return api_error(400, "Target is not a participant", "validation_error")

    with _db.acquire_sync() as conn:
        conn.execute(
            "UPDATE chat.webchat_participants SET role = 'member' "
            "WHERE conversation_id = %s AND unified_id = %s",
            (conv_id, uid),
        )
        conn.execute(
            "UPDATE chat.webchat_participants SET role = 'owner' "
            "WHERE conversation_id = %s AND unified_id = %s",
            (conv_id, new_owner),
        )
        conn.commit()
    return api_ok()


@router.post(
    "/conversations/{conv_id}/remove-participant",
    response_model=ApiResponse,
    response_model_exclude_none=True,
)
async def remove_participant(
    request: Request, conv_id: str, user: dict = Depends(require_user)
):
    """Remove a participant from the conversation. Owner only."""
    _ensure_db()
    uid = _uid(user)
    if not is_conversation_owner(conv_id, uid):
        return api_error(403, "Only the owner can remove participants", "forbidden")

    body = await request.json()
    target = body.get("username", "").strip().lower()
    if not target or target == uid:
        return api_error(400, "Invalid target", "validation_error")

    with _db.acquire_sync() as conn:
        conn.execute(
            "DELETE FROM chat.webchat_participants "
            "WHERE conversation_id = %s AND unified_id = %s",
            (conv_id, target),
        )
        conn.commit()

    from ui.routes.ws_chat import push_to_webchat

    await push_to_webchat(
        target, {"type": "participant_removed", "conversation_id": conv_id}
    )
    return api_ok()


# --- File upload ---


@router.post(
    "/upload",
    response_model=ApiResponse[dict],
    response_model_exclude_none=True,
)
async def upload_file(request: Request, user: dict = Depends(require_user)):
    """Upload a file for chat attachment. Returns the server-side file path."""
    uid = _uid(user)

    form = await request.form()
    file: UploadFile | None = form.get("file")
    if not file or not file.filename:
        return api_error(400, "No file provided", "validation_error")

    # Validate extension
    from handlers.attachment_handler import sanitize_filename

    safe_name = sanitize_filename(file.filename)
    ext = Path(safe_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return api_error(400, f"File type {ext} not allowed", "validation_error")

    # Read with size limit
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        return api_error(400, "File too large (max 20MB)", "validation_error")

    # Save to user-specific directory with timestamp prefix to avoid collisions
    user_dir = ATTACHMENTS_DIR / "webchat" / uid
    user_dir.mkdir(parents=True, exist_ok=True)
    dest_name = f"{int(time.time())}_{safe_name}"
    dest_path = user_dir / dest_name
    dest_path.write_bytes(content)

    logger.info(f"WebChat upload: {uid} -> {dest_path} ({len(content)} bytes)")

    return api_ok(
        data={
            "path": str(dest_path),
            "filename": safe_name,
            "size": len(content),
        }
    )


# --- Bot file delivery ---

OUTBOUND_DIR = ATTACHMENTS_DIR / "webchat-outbound"

# Token store: {token: {"path": str, "uid": str, "expires": float}}
_file_tokens: dict[str, dict] = {}
_FILE_TOKEN_TTL = 3600  # 1 hour


def create_file_token(
    file_path: str, uid: str, conversation_id: str | None = None
) -> str:
    """Create a short-lived token to serve a file to a specific user."""
    import secrets

    token = secrets.token_urlsafe(32)
    _file_tokens[token] = {
        "path": file_path,
        "uid": uid,
        "conversation_id": conversation_id,
        "expires": time.time() + _FILE_TOKEN_TTL,
    }
    # Prune expired tokens periodically (every 100 creates)
    if len(_file_tokens) % 100 == 0:
        now = time.time()
        expired = [k for k, v in _file_tokens.items() if v["expires"] < now]
        for k in expired:
            del _file_tokens[k]
    return token


@router.get("/files/{token}")
async def serve_file(token: str, user: dict = Depends(require_user)):
    """Serve a bot-delivered file via token-based access."""
    entry = _file_tokens.get(token)
    if not entry:
        return api_error(404, "File not found or expired", "not_found")

    if entry["expires"] < time.time():
        _file_tokens.pop(token, None)
        return api_error(404, "File expired", "not_found")

    uid = _uid(user)
    if entry["uid"] != uid:
        # Allow access if user is a participant of the same conversation
        conv_id = entry.get("conversation_id")
        if not conv_id or not validate_conversation_access(conv_id, uid):
            return api_error(403, "Access denied", "forbidden")

    file_path = Path(entry["path"])
    if not file_path.exists():
        _file_tokens.pop(token, None)
        return api_error(404, "File no longer available", "not_found")

    import mimetypes

    content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    return FileResponse(file_path, media_type=content_type)


# --- TTS ---


def _strip_markdown(text: str) -> str:
    """Remove markdown formatting for cleaner TTS input."""
    text = re.sub(r"```[\s\S]*?```", " code block ", text)
    text = re.sub(r"`[^`]+`", lambda m: m.group(0)[1:-1], text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[#*_~>|]", "", text)
    text = re.sub(r"\n{2,}", ". ", text)
    text = text.replace("\n", " ").strip()
    return text


@router.get(
    "/tts/config",
    response_model=ApiResponse[dict],
    response_model_exclude_none=True,
)
async def tts_config(user: dict = Depends(require_user)):
    """Return the current TTS provider setting."""
    from ui.config_manager import ConfigManager

    config = ConfigManager()
    return api_ok(data={"provider": config.get_webchat_tts_provider()})


@router.post("/tts")
async def tts_synthesize(request: Request, user: dict = Depends(require_user)):
    """Synthesize text to speech and return audio file."""
    from ui import tts_service
    from ui.config_manager import ConfigManager

    try:
        body = await request.json()
    except Exception:
        return api_error(400, "Invalid JSON", "validation_error")

    text = (body.get("text") or "").strip()
    if not text:
        return api_error(400, "No text provided", "validation_error")

    clean_text = _strip_markdown(text)
    if not clean_text:
        return api_error(400, "No speakable text", "validation_error")

    config = ConfigManager()
    provider = config.get_webchat_tts_provider()

    try:
        file_path = await tts_service.synthesize(clean_text, provider, locale="it")
    except Exception as e:
        logger.error(f"TTS synthesis error ({provider}): {e}")
        return api_error(500, "TTS synthesis failed", "internal_error")

    if not file_path:
        return api_error(400, "Provider is browser", "browser_tts")

    return FileResponse(
        file_path,
        media_type="audio/mpeg",
        background=BackgroundTask(os.unlink, file_path),
    )
