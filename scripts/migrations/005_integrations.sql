-- Migration: 005_integrations
-- Video-call, LiveKit, Videomaker, Odoo Apps Indexer -> app schema
-- MS365 tokens -> vault schema

-- ============================================================
-- app schema: video-call meetings
-- ============================================================

CREATE TABLE IF NOT EXISTS app.meetings (
    id TEXT PRIMARY KEY,
    meeting_url TEXT NOT NULL,
    platform TEXT NOT NULL,
    status TEXT NOT NULL,
    bot_id TEXT,
    agent_name TEXT,
    title TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    summary TEXT,
    metadata JSONB
);
CREATE INDEX IF NOT EXISTS idx_meetings_bot_id ON app.meetings(bot_id);
CREATE INDEX IF NOT EXISTS idx_meetings_status ON app.meetings(status);

CREATE TABLE IF NOT EXISTS app.meeting_participants (
    meeting_id TEXT NOT NULL REFERENCES app.meetings(id) ON DELETE CASCADE,
    participant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    is_bot BOOLEAN DEFAULT FALSE,
    joined_at TIMESTAMPTZ,
    left_at TIMESTAMPTZ,
    PRIMARY KEY (meeting_id, participant_id)
);

CREATE TABLE IF NOT EXISTS app.meeting_utterances (
    id TEXT PRIMARY KEY,
    meeting_id TEXT NOT NULL REFERENCES app.meetings(id) ON DELETE CASCADE,
    speaker_id TEXT NOT NULL,
    speaker_name TEXT NOT NULL,
    text TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    confidence REAL DEFAULT 1.0,
    is_final BOOLEAN DEFAULT TRUE,
    language TEXT DEFAULT 'en'
);
CREATE INDEX IF NOT EXISTS idx_utterances_meeting
    ON app.meeting_utterances(meeting_id, timestamp);

-- ============================================================
-- app schema: livekit sessions
-- ============================================================

CREATE TABLE IF NOT EXISTS app.livekit_sessions (
    room_name TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    user_name TEXT,
    user_token TEXT NOT NULL,
    agent_token TEXT NOT NULL,
    ws_url TEXT NOT NULL,
    cleanup_token TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    end_reason TEXT
);

-- ============================================================
-- app schema: videomaker projects
-- ============================================================

CREATE TABLE IF NOT EXISTS app.videomaker_projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    resolution_w INTEGER NOT NULL,
    resolution_h INTEGER NOT NULL,
    fps INTEGER NOT NULL DEFAULT 30,
    status TEXT NOT NULL DEFAULT 'created',
    segments_json JSONB DEFAULT '[]'::jsonb,
    narration_json JSONB DEFAULT '[]'::jsonb,
    overlays_json JSONB DEFAULT '[]'::jsonb,
    chapters_json JSONB DEFAULT '[]'::jsonb,
    intro_config_json JSONB,
    output_dir TEXT,
    final_video TEXT,
    agent_name TEXT,
    chat_id TEXT,
    platform TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- app schema: odoo-apps-indexer (with tsvector FTS)
-- ============================================================

CREATE TABLE IF NOT EXISTS app.odoo_apps (
    id SERIAL PRIMARY KEY,
    technical_name TEXT NOT NULL,
    name TEXT,
    summary TEXT,
    description TEXT,
    version TEXT,
    odoo_version TEXT NOT NULL,
    author TEXT,
    category TEXT,
    license TEXT,
    website TEXT,
    source TEXT NOT NULL,
    source_repo TEXT,
    source_url TEXT,
    is_application BOOLEAN DEFAULT FALSE,
    installable BOOLEAN DEFAULT TRUE,
    indexed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    search_tsv TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('simple',
            coalesce(technical_name, '') || ' ' ||
            coalesce(name, '') || ' ' ||
            coalesce(summary, '') || ' ' ||
            coalesce(description, '') || ' ' ||
            coalesce(author, '') || ' ' ||
            coalesce(category, '')
        )
    ) STORED,
    UNIQUE(technical_name, odoo_version, source)
);
CREATE INDEX IF NOT EXISTS idx_odoo_apps_fts ON app.odoo_apps USING GIN (search_tsv);
CREATE INDEX IF NOT EXISTS idx_odoo_apps_version ON app.odoo_apps(odoo_version);
CREATE INDEX IF NOT EXISTS idx_odoo_apps_source ON app.odoo_apps(source);

CREATE TABLE IF NOT EXISTS app.odoo_app_depends (
    app_id INTEGER NOT NULL REFERENCES app.odoo_apps(id) ON DELETE CASCADE,
    depend_name TEXT NOT NULL,
    PRIMARY KEY (app_id, depend_name)
);

CREATE TABLE IF NOT EXISTS app.odoo_index_metadata (
    source TEXT NOT NULL,
    odoo_version TEXT NOT NULL,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    apps_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'idle',
    error_message TEXT,
    tree_sha TEXT,
    PRIMARY KEY (source, odoo_version)
);

-- ============================================================
-- vault schema: ms365 tokens
-- ============================================================

CREATE TABLE IF NOT EXISTS vault.ms365_tokens (
    tenant_id TEXT PRIMARY KEY,
    tenant_name TEXT,
    access_token_encrypted BYTEA,
    refresh_token_encrypted BYTEA,
    expires_at TIMESTAMPTZ,
    scopes TEXT,
    capabilities TEXT,
    capabilities_cached_at TIMESTAMPTZ,
    role TEXT DEFAULT 'guest',
    status TEXT DEFAULT 'active',
    failure_count INTEGER DEFAULT 0,
    schema_version INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
