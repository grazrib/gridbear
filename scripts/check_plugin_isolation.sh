#!/usr/bin/env bash
# check_plugin_isolation.sh
# Ensures core/ and ui/ never reference plugins directly.

set -euo pipefail

ERRORS=0
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

echo "=== Plugin Isolation Check ==="

# 1. No imports from plugins/ in core/ or ui/
# Match only actual import statements (lines starting with from/import after whitespace)
# Excludes comments (#) and strings containing "plugins."
echo -n "Checking core/ for plugin imports... "
HITS=$(grep -rn "^\s*from plugins\.\|^\s*import plugins\." core/ --include="*.py" 2>/dev/null | grep -v "__pycache__" || true)
if [ -n "$HITS" ]; then
    echo -e "${RED}FAIL${NC}"
    echo "$HITS"
    ERRORS=$((ERRORS + 1))
else
    echo -e "${GREEN}OK${NC}"
fi

echo -n "Checking ui/ for plugin imports... "
HITS=$(grep -rn "^\s*from plugins\.\|^\s*import plugins\." ui/ --include="*.py" 2>/dev/null | grep -v "__pycache__" || true)
if [ -n "$HITS" ]; then
    echo -e "${RED}FAIL${NC}"
    echo "$HITS"
    ERRORS=$((ERRORS + 1))
else
    echo -e "${GREEN}OK${NC}"
fi

# 2. No plugin-specific templates in ui/templates/plugins/
# Only these framework files are allowed:
ALLOWED_FILES=(
    "plugin_base.html"
    "plugin_subpage.html"
    "config.html"
    "list.html"
    "paths.html"
)

echo -n "Checking ui/templates/plugins/ for stray templates... "
STRAY=""
if [ -d "ui/templates/plugins" ]; then
    for f in ui/templates/plugins/*.html; do
        [ -f "$f" ] || continue
        BASENAME=$(basename "$f")
        ALLOWED=false
        for a in "${ALLOWED_FILES[@]}"; do
            if [ "$BASENAME" = "$a" ]; then
                ALLOWED=true
                break
            fi
        done
        if [ "$ALLOWED" = false ]; then
            STRAY="$STRAY  $f\n"
        fi
    done
fi

if [ -n "$STRAY" ]; then
    echo -e "${RED}FAIL${NC}"
    echo -e "Plugin-specific templates must live in plugins/{name}/admin/templates/:"
    echo -e "$STRAY"
    ERRORS=$((ERRORS + 1))
else
    echo -e "${GREEN}OK${NC}"
fi

echo ""
if [ $ERRORS -gt 0 ]; then
    echo -e "${RED}Found $ERRORS violation(s). Fix before committing.${NC}"
    exit 1
else
    echo -e "${GREEN}All checks passed.${NC}"
    exit 0
fi
