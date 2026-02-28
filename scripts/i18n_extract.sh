#!/bin/bash
# Extract translatable strings from GridBear source.
#
# Usage:
#   ./scripts/i18n_extract.sh          # extract all domains
#   ./scripts/i18n_extract.sh ui       # extract UI domain only
#   ./scripts/i18n_extract.sh telegram # extract a single plugin

set -e

DOMAIN="${1:-all}"
BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"

extract_ui() {
    echo "Extracting UI domain..."
    pybabel extract -F "$BASE_DIR/babel.cfg" \
        -o "$BASE_DIR/ui/i18n/ui.pot" \
        --project=GridBear \
        "$BASE_DIR"
    echo "  -> ui/i18n/ui.pot"
}

extract_plugin() {
    local plugin="$1"
    local plugin_dir="$BASE_DIR/plugins/$plugin"
    if [ ! -d "$plugin_dir/i18n" ]; then
        echo "  Skipping $plugin (no i18n/ directory)"
        return
    fi
    echo "  Extracting $plugin..."
    pybabel extract -F "$BASE_DIR/babel-plugin.cfg" \
        -o "$plugin_dir/i18n/$plugin.pot" \
        --project=GridBear \
        "$plugin_dir"
    echo "  -> plugins/$plugin/i18n/$plugin.pot"
}

case "$DOMAIN" in
    all)
        extract_ui
        echo "Extracting plugin domains..."
        for dir in "$BASE_DIR"/plugins/*/i18n; do
            plugin=$(basename "$(dirname "$dir")")
            extract_plugin "$plugin"
        done
        ;;
    ui)
        extract_ui
        ;;
    *)
        extract_plugin "$DOMAIN"
        ;;
esac

echo "Done."
