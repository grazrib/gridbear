#!/usr/bin/env bash
# Migrate CLI auth data from host directories to Docker named volumes.
#
# Run ONCE after switching from bind mounts to named volumes in docker-compose.yml.
# This copies existing ~/.claude and ~/.codex auth data into the claude_state
# and codex_state Docker volumes so you don't need to re-authenticate.
#
# Usage:
#   ./scripts/migrate_cli_auth.sh
#
# Prerequisites:
#   - Docker volumes must exist (run `docker compose up -d` first, then stop)
#   - Host directories ~/.claude and/or ~/.codex must contain auth data

set -euo pipefail

PROJECT_NAME="${COMPOSE_PROJECT_NAME:-gridbear}"
CLAUDE_VOLUME="${PROJECT_NAME}_claude_state"
CODEX_VOLUME="${PROJECT_NAME}_codex_state"

migrate_dir_to_volume() {
    local src_dir="$1"
    local volume_name="$2"
    local label="$3"

    if [ ! -d "$src_dir" ]; then
        echo "  SKIP $label: $src_dir does not exist"
        return
    fi

    # Check if volume exists
    if ! docker volume inspect "$volume_name" &>/dev/null; then
        echo "  SKIP $label: volume $volume_name does not exist"
        echo "       Run 'docker compose up -d && docker compose down' first to create volumes"
        return
    fi

    # Check if volume already has auth data
    local has_data
    has_data=$(docker run --rm -v "$volume_name":/target alpine sh -c \
        'test -f /target/.claude.json 2>/dev/null || test -f /target/credentials.json 2>/dev/null; echo $?')
    if [ "$has_data" = "0" ]; then
        echo "  SKIP $label: volume $volume_name already contains data"
        echo "       Delete volume first if you want to re-migrate: docker volume rm $volume_name"
        return
    fi

    echo "  Copying $src_dir -> volume $volume_name ..."
    docker run --rm \
        -v "$src_dir":/source:ro \
        -v "$volume_name":/target \
        alpine sh -c 'cp -a /source/. /target/ && chown -R 1000:1000 /target/'

    echo "  OK $label migrated successfully"
}

echo "GridBear CLI Auth Migration"
echo "==========================="
echo ""
echo "Project: $PROJECT_NAME"
echo ""

migrate_dir_to_volume "$HOME/.claude" "$CLAUDE_VOLUME" "Claude CLI"
migrate_dir_to_volume "$HOME/.codex"  "$CODEX_VOLUME"  "Codex CLI"

echo ""
echo "Done. Start GridBear with: docker compose up -d"
