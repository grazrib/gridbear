-- Migration: 004_apps_webchat
-- Skills, memo prompts, scheduled memos/tasks -> app schema
-- WebChat conversations and messages -> chat schema

-- ============================================================
-- app schema: skills
-- ============================================================

CREATE TABLE IF NOT EXISTS app.skills (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT,
    prompt TEXT NOT NULL,
    category TEXT DEFAULT 'other',
    plugin_name TEXT,
    skill_type TEXT DEFAULT 'user',
    created_by BIGINT,
    created_by_platform TEXT,
    shared BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_skills_category ON app.skills(category);
CREATE INDEX IF NOT EXISTS idx_skills_name ON app.skills(name);
CREATE INDEX IF NOT EXISTS idx_skills_plugin ON app.skills(plugin_name);
CREATE INDEX IF NOT EXISTS idx_skills_type ON app.skills(skill_type);

-- ============================================================
-- app schema: memo prompts (reusable prompt templates)
-- ============================================================

CREATE TABLE IF NOT EXISTS app.memo_prompts (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    platform TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- app schema: scheduled memos (references prompts)
-- ============================================================

CREATE TABLE IF NOT EXISTS app.scheduled_memos (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    platform TEXT NOT NULL,
    prompt_id INTEGER NOT NULL REFERENCES app.memo_prompts(id) ON DELETE CASCADE,
    schedule_type TEXT NOT NULL,
    cron TEXT,
    run_at TEXT,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_run TIMESTAMPTZ
);

-- ============================================================
-- app schema: scheduled tasks (legacy TaskScheduler)
-- ============================================================

CREATE TABLE IF NOT EXISTS app.scheduled_tasks (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    platform TEXT NOT NULL,
    schedule_type TEXT NOT NULL,
    cron TEXT,
    run_at TEXT,
    prompt TEXT NOT NULL,
    description TEXT,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_run TIMESTAMPTZ
);

-- ============================================================
-- chat schema: webchat conversations
-- ============================================================

CREATE TABLE IF NOT EXISTS chat.webchat_conversations (
    id TEXT PRIMARY KEY,
    unified_id TEXT NOT NULL,
    agent_name TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_webchat_conv_user_agent
    ON chat.webchat_conversations(unified_id, agent_name, updated_at DESC);

-- ============================================================
-- chat schema: webchat messages
-- ============================================================

CREATE TABLE IF NOT EXISTS chat.webchat_messages (
    id SERIAL PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES chat.webchat_conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    metadata_json TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_webchat_msg_conv
    ON chat.webchat_messages(conversation_id, created_at ASC);
