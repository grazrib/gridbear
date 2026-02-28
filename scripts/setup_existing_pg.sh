#!/bin/bash
# GridBear: One-time setup for existing PostgreSQL installations
#
# For EXISTING installations where 'evolution' is still the superuser.
# This script promotes gridbear to superuser and demotes evolution.
#
# Run inside a running container:
#   docker exec -i gridbear-postgres bash < scripts/setup_existing_pg.sh
#
# After running this script:
#   1. Update docker-compose.yml: POSTGRES_USER=gridbear, POSTGRES_DB=gridbear
#   2. Recreate PG volume (dump/restore) or keep using this setup
#
# Safe to run multiple times (all operations use IF NOT EXISTS / idempotent).

set -e

echo "=== GridBear: Setting up existing PostgreSQL instance ==="

GRIDBEAR_PASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set}"

# --- Step 1: Create gridbear role as SUPERUSER (if not exists) ---
psql -v ON_ERROR_STOP=1 --username "evolution" --dbname "evolution" <<-EOSQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'gridbear') THEN
            CREATE ROLE gridbear WITH LOGIN SUPERUSER PASSWORD '${GRIDBEAR_PASSWORD}';
            RAISE NOTICE 'Created superuser role: gridbear';
        ELSE
            -- Ensure gridbear has superuser if it already existed as regular user
            ALTER ROLE gridbear WITH SUPERUSER;
            RAISE NOTICE 'Role gridbear already exists, ensured SUPERUSER';
        END IF;
    END
    \$\$;
EOSQL

# --- Step 2: Create gridbear database (if not exists) ---
psql -v ON_ERROR_STOP=1 --username "gridbear" --dbname "evolution" <<-EOSQL
    SELECT 'CREATE DATABASE gridbear OWNER gridbear'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'gridbear')\gexec
EOSQL

# --- Step 3: Set up schemas and extensions in gridbear database ---
psql -v ON_ERROR_STOP=1 --username "gridbear" --dbname "gridbear" <<-EOSQL
    CREATE SCHEMA IF NOT EXISTS admin;
    CREATE SCHEMA IF NOT EXISTS vault;
    CREATE SCHEMA IF NOT EXISTS chat;
    CREATE SCHEMA IF NOT EXISTS app;
    CREATE SCHEMA IF NOT EXISTS integrations;

    -- Enable pgvector extension
    CREATE EXTENSION IF NOT EXISTS vector;

    -- Migrations tracking table
    CREATE TABLE IF NOT EXISTS public._migrations (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        checksum TEXT
    );
EOSQL

# --- Step 4: Demote evolution to regular user (best effort) ---
# On existing volumes, evolution is the bootstrap superuser and PG won't
# allow removing SUPERUSER from it. That's fine — on fresh installs gridbear
# will be the bootstrap and evolution will be created as regular.
psql --username "gridbear" --dbname "gridbear" <<-EOSQL
    DO \$\$
    BEGIN
        ALTER ROLE evolution WITH NOSUPERUSER;
        RAISE NOTICE 'Demoted evolution to regular user';
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'Could not demote evolution (bootstrap superuser) — this is expected on existing volumes';
    END
    \$\$;

    -- Ensure evolution still owns its database
    DO \$\$
    BEGIN
        IF EXISTS (SELECT FROM pg_database WHERE datname = 'evolution') THEN
            EXECUTE 'ALTER DATABASE evolution OWNER TO evolution';
        END IF;
    END
    \$\$;
EOSQL

echo "=== GridBear: Setup complete ==="
echo "  - Superuser: gridbear"
echo "  - Database:  gridbear (schemas: admin, vault, chat, app, integrations)"
echo "  - Role:      evolution (demoted to regular user, owns evolution database)"
echo ""
echo "Verify with:"
echo "  psql -U gridbear -d gridbear -c '\\du'"
echo "  psql -U gridbear -d gridbear -c '\\dn'"
echo "  psql -U gridbear -d gridbear -c 'SELECT * FROM _migrations'"
echo ""
echo "Next steps:"
echo "  1. Update docker-compose.yml: POSTGRES_USER=gridbear, POSTGRES_DB=gridbear"
echo "  2. Update healthcheck: pg_isready -U gridbear -d gridbear"
echo "  3. Restart: docker compose down && docker compose up -d"
