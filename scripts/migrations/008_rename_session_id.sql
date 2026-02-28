-- Migration: 008_rename_session_id
-- Rename claude_session_id → runner_session_id to decouple from specific runner

ALTER TABLE chat.sessions
    RENAME COLUMN claude_session_id TO runner_session_id;
