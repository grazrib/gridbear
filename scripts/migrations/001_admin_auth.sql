-- Migration: 001_admin_auth
-- Admin authentication tables (migrated from SQLite admin_auth.db + user_preferences.db)

-- Admin users
CREATE TABLE IF NOT EXISTS admin.users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    email TEXT,
    password_hash TEXT NOT NULL,
    totp_secret TEXT,
    totp_enabled BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    is_superadmin BOOLEAN DEFAULT FALSE,
    unified_id TEXT,
    display_name TEXT,
    avatar_url TEXT,
    locale TEXT DEFAULT 'en',
    webauthn_enabled BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_login TIMESTAMPTZ,
    failed_login_attempts INTEGER DEFAULT 0,
    lockout_until TIMESTAMPTZ
);

-- Recovery codes (bcrypt hash, one-time use)
CREATE TABLE IF NOT EXISTS admin.recovery_codes (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES admin.users(id) ON DELETE CASCADE,
    code_hash TEXT NOT NULL,
    used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Persistent admin sessions
CREATE TABLE IF NOT EXISTS admin.sessions (
    id SERIAL PRIMARY KEY,
    session_token TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES admin.users(id) ON DELETE CASCADE,
    ip_address TEXT,
    user_agent TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    last_activity TIMESTAMPTZ
);

-- Audit log for security events
CREATE TABLE IF NOT EXISTS admin.audit_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER,
    username TEXT,
    event_type TEXT NOT NULL,
    ip_address TEXT,
    success BOOLEAN,
    details TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- WebAuthn / passkeys credentials
CREATE TABLE IF NOT EXISTS admin.webauthn_credentials (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES admin.users(id) ON DELETE CASCADE,
    credential_id BYTEA NOT NULL UNIQUE,
    public_key BYTEA NOT NULL,
    sign_count INTEGER DEFAULT 0,
    device_name TEXT DEFAULT 'Security Key',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_used_at TIMESTAMPTZ
);

-- User tool preferences (migrated from user_preferences.db)
CREATE TABLE IF NOT EXISTS admin.user_tool_preferences (
    id SERIAL PRIMARY KEY,
    unified_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(unified_id, tool_name)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_users_unified_id ON admin.users(unified_id);
CREATE INDEX IF NOT EXISTS idx_sessions_token ON admin.sessions(session_token);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON admin.sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON admin.sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_recovery_user ON admin.recovery_codes(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_user ON admin.audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON admin.audit_log(created_at);
CREATE INDEX IF NOT EXISTS idx_webauthn_user ON admin.webauthn_credentials(user_id);
CREATE INDEX IF NOT EXISTS idx_webauthn_credential ON admin.webauthn_credentials(credential_id);
CREATE INDEX IF NOT EXISTS idx_tool_prefs_uid ON admin.user_tool_preferences(unified_id);
