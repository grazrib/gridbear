-- Migration: 002_secrets_oauth2
-- Secrets vault and OAuth2 tables (migrated from SQLite secrets.db + oauth2.db)

-- Create oauth2 schema (vault already exists from init_pg.sh)
CREATE SCHEMA IF NOT EXISTS oauth2;

-- ============================================================
-- Vault: Encrypted secrets storage
-- ============================================================

CREATE TABLE IF NOT EXISTS vault.secrets (
    key_name TEXT PRIMARY KEY,
    encrypted_value TEXT NOT NULL,
    nonce TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- OAuth2: Clients
-- ============================================================

CREATE TABLE IF NOT EXISTS oauth2.clients (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    client_id TEXT NOT NULL UNIQUE,
    client_secret_hash TEXT,
    client_type TEXT NOT NULL CHECK(client_type IN ('confidential', 'public')) DEFAULT 'confidential',
    redirect_uris TEXT,
    allowed_scopes TEXT DEFAULT 'openid profile email',
    access_token_expiry INTEGER DEFAULT 3600,
    refresh_token_expiry INTEGER DEFAULT 2592000,
    require_pkce BOOLEAN DEFAULT TRUE,
    agent_name TEXT,
    gridbear_user_id TEXT,
    mcp_permissions TEXT,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    description TEXT
);

-- ============================================================
-- OAuth2: Authorization codes
-- ============================================================

CREATE TABLE IF NOT EXISTS oauth2.authorization_codes (
    id SERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    client_id INTEGER NOT NULL REFERENCES oauth2.clients(id),
    user_identity TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    scope TEXT,
    code_challenge TEXT,
    code_challenge_method TEXT DEFAULT 'S256',
    state TEXT,
    expires_at TIMESTAMPTZ NOT NULL,
    used BOOLEAN DEFAULT FALSE
);

-- ============================================================
-- OAuth2: Access tokens
-- ============================================================

CREATE TABLE IF NOT EXISTS oauth2.access_tokens (
    id SERIAL PRIMARY KEY,
    token TEXT NOT NULL UNIQUE,
    token_type TEXT DEFAULT 'Bearer',
    client_id INTEGER NOT NULL REFERENCES oauth2.clients(id),
    user_identity TEXT,
    scope TEXT,
    expires_at TIMESTAMPTZ NOT NULL,
    refresh_token TEXT UNIQUE,
    refresh_expires_at TIMESTAMPTZ,
    revoked BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_used_at TIMESTAMPTZ,
    ip_address TEXT,
    user_agent TEXT
);

-- ============================================================
-- Indexes
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_oauth2_client_client_id ON oauth2.clients(client_id);
CREATE INDEX IF NOT EXISTS idx_oauth2_client_agent ON oauth2.clients(agent_name);
CREATE INDEX IF NOT EXISTS idx_oauth2_auth_code ON oauth2.authorization_codes(code);
CREATE INDEX IF NOT EXISTS idx_oauth2_auth_expires ON oauth2.authorization_codes(expires_at);
CREATE INDEX IF NOT EXISTS idx_oauth2_token_token ON oauth2.access_tokens(token);
CREATE INDEX IF NOT EXISTS idx_oauth2_token_refresh ON oauth2.access_tokens(refresh_token);
CREATE INDEX IF NOT EXISTS idx_oauth2_token_client ON oauth2.access_tokens(client_id);
CREATE INDEX IF NOT EXISTS idx_oauth2_token_expires ON oauth2.access_tokens(expires_at);
