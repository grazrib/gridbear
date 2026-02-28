#!/bin/bash
# GridBear PostgreSQL initialization script
# Runs automatically on first container creation (empty data dir) via docker-entrypoint-initdb.d
#
# POSTGRES_USER=gridbear is the superuser (created automatically by the PG image).
# This script creates:
#   1. Schemas (admin, vault, chat, app, integrations) in the gridbear database
#   2. _migrations tracking table
#   3. pgvector extension
#   4. evolution role + evolution database (for Evolution API / WhatsApp plugin)

set -e

echo "=== GridBear: Initializing PostgreSQL ==="

EVOLUTION_PASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set}"

# --- gridbear database setup (already created by POSTGRES_DB=gridbear) ---
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Create schemas owned by gridbear (the superuser)
    CREATE SCHEMA IF NOT EXISTS admin;
    CREATE SCHEMA IF NOT EXISTS vault;
    CREATE SCHEMA IF NOT EXISTS oauth2;
    CREATE SCHEMA IF NOT EXISTS chat;
    CREATE SCHEMA IF NOT EXISTS app;
    CREATE SCHEMA IF NOT EXISTS integrations;

    -- Enable pgvector extension
    CREATE EXTENSION IF NOT EXISTS vector;

    -- Migrations tracking table in public schema
    CREATE TABLE IF NOT EXISTS public._migrations (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        checksum TEXT
    );
EOSQL

# --- evolution role + database (for Evolution API) ---
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'evolution') THEN
            CREATE ROLE evolution WITH LOGIN PASSWORD '${EVOLUTION_PASSWORD}';
            RAISE NOTICE 'Created role: evolution';
        END IF;
    END
    \$\$;

    SELECT 'CREATE DATABASE evolution OWNER evolution'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'evolution')\gexec
EOSQL

# --- n8n database (for N8N workflow automation) ---
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    SELECT 'CREATE DATABASE n8n OWNER gridbear'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'n8n')\gexec
EOSQL

echo "=== GridBear: PostgreSQL initialization complete ==="
echo "  - Superuser: gridbear (POSTGRES_USER)"
echo "  - Database:  gridbear (schemas: admin, vault, oauth2, chat, app, integrations)"
echo "  - Database:  n8n (for N8N workflow automation)"
echo "  - Extension: pgvector"
echo "  - Role:      evolution (regular user, owns evolution database)"
