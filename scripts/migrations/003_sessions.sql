-- Migration: 003_sessions
-- Chat sessions, messages, and persistent chat history (migrated from SQLite sessions.db)

-- Schema 'chat' already created by init_pg.sh

-- ============================================================
-- Sessions: Active user sessions with TTL
-- ============================================================

CREATE TABLE IF NOT EXISTS chat.sessions (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    platform TEXT NOT NULL,
    runner_session_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_platform
    ON chat.sessions(user_id, platform);

-- ============================================================
-- Messages: Per-session message history (legacy, kept for compat)
-- ============================================================

CREATE TABLE IF NOT EXISTS chat.messages (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES chat.sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- Chat History: Persistent cross-session history with FTS
-- ============================================================

CREATE TABLE IF NOT EXISTS chat.chat_history (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    platform TEXT NOT NULL,
    username TEXT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    content_tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED
);

CREATE INDEX IF NOT EXISTS idx_chat_history_user
    ON chat.chat_history(user_id, platform, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_chat_history_fts
    ON chat.chat_history USING GIN (content_tsv);
