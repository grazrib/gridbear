#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'USAGE'
Usage: ./install.sh [options]

Options:
  --with-override     Copy docker-compose.override.yml.example if missing
  --no-build          Do not build images (use pull/up only)
  --no-pull           Do not pull images before starting
  --no-up             Only prepare files (.env, folders) without starting containers
  --base-url URL      Set GRIDBEAR_BASE_URL in .env if missing (default: http://localhost:8088)
  -h, --help          Show this help
USAGE
}

WITH_OVERRIDE=0
NO_BUILD=0
NO_PULL=0
NO_UP=0
BASE_URL_DEFAULT="http://localhost:8088"
BASE_URL_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-override) WITH_OVERRIDE=1; shift ;;
    --no-build) NO_BUILD=1; shift ;;
    --no-pull) NO_PULL=1; shift ;;
    --no-up) NO_UP=1; shift ;;
    --base-url)
      BASE_URL_OVERRIDE="${2:-}"
      shift 2
      ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Argomento non riconosciuto: $1" >&2
      usage
      exit 2
      ;;
  esac
done

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "Comando mancante: $1" >&2; exit 1; }
}

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "Questo script è pensato per Linux (Ubuntu)." >&2
  exit 1
fi

need_cmd docker
if ! docker info >/dev/null 2>&1; then
  echo "Docker non sembra in esecuzione. Avvia il daemon e riprova." >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 non trovato. Assicurati di avere 'docker compose' disponibile." >&2
  exit 1
fi

cd "$ROOT_DIR"

if [[ ! -f ".env.example" ]]; then
  echo "File .env.example non trovato." >&2
  exit 1
fi

gen_secret_hex() {
  local bytes="$1"
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$bytes"
    return 0
  fi
  python3 - <<PY
import secrets
print(secrets.token_hex($bytes))
PY
}

gen_secret_b64() {
  local bytes="$1"
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 "$bytes" | tr -d '\n'
    return 0
  fi
  python3 - <<PY
import secrets, base64
print(base64.b64encode(secrets.token_bytes($bytes)).decode("ascii"))
PY
}

normalize_env_value() {
  printf "%s" "$1" | tr -d '\r' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
}

is_url_safe_userinfo() {
  [[ "$1" =~ ^[A-Za-z0-9._~-]+$ ]]
}

BASE_URL_TO_SET="$BASE_URL_DEFAULT"
if [[ -n "$BASE_URL_OVERRIDE" ]]; then
  BASE_URL_TO_SET="$BASE_URL_OVERRIDE"
fi
BASE_URL_TO_SET="${BASE_URL_TO_SET%/}"
if [[ -z "$BASE_URL_TO_SET" ]]; then
  BASE_URL_TO_SET="$BASE_URL_DEFAULT"
fi

URL_WITHOUT_SCHEME="${BASE_URL_TO_SET#*://}"
URL_HOST_PORT="${URL_WITHOUT_SCHEME%%/*}"
WEBAUTHN_RP_ID_DEFAULT="${URL_HOST_PORT%%:*}"
if [[ -z "$WEBAUTHN_RP_ID_DEFAULT" ]]; then
  WEBAUTHN_RP_ID_DEFAULT="localhost"
fi

POSTGRES_PASSWORD_VALUE="$(gen_secret_hex 24)"
INTERNAL_API_SECRET_VALUE="$(gen_secret_hex 32)"
EXECUTOR_TOKEN_VALUE="$(gen_secret_hex 32)"

if [[ -f ".env" ]]; then
  cp ".env" ".env.bak"
fi

TMP_ENV_FILE=".env.tmp.$$"
>"$TMP_ENV_FILE"

while IFS= read -r line || [[ -n "$line" ]]; do
  if [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]]; then
    printf "%s\n" "$line" >>"$TMP_ENV_FILE"
    continue
  fi

  if [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
    key="${BASH_REMATCH[1]}"
    value="${BASH_REMATCH[2]}"
    value="$(normalize_env_value "$value")"
    existing_value=""
    if [[ -f ".env" ]]; then
      existing_line="$(grep -E "^${key}=" ".env" | tail -n 1 || true)"
      if [[ -n "$existing_line" ]]; then
        existing_value="${existing_line#*=}"
      fi
    fi
    existing_value="$(normalize_env_value "$existing_value")"
    if [[ -n "$existing_value" ]]; then
      value="$existing_value"
    fi

    case "$key" in
      POSTGRES_PASSWORD)
        if [[ -z "$value" ]] || ! is_url_safe_userinfo "$value"; then
          value="$POSTGRES_PASSWORD_VALUE"
        fi
        ;;
      INTERNAL_API_SECRET)
        if [[ -z "$value" ]]; then
          value="$INTERNAL_API_SECRET_VALUE"
        fi
        ;;
      EXECUTOR_TOKEN)
        if [[ -z "$value" ]]; then
          value="$EXECUTOR_TOKEN_VALUE"
        fi
        ;;
      GRIDBEAR_BASE_URL)
        value="$BASE_URL_TO_SET"
        ;;
      WEBAUTHN_ORIGIN)
        value="$BASE_URL_TO_SET"
        ;;
      WEBAUTHN_RP_ID)
        if [[ -z "$value" ]]; then
          value="$WEBAUTHN_RP_ID_DEFAULT"
        fi
        ;;
    esac

    printf "%s=%s\n" "$key" "$value" >>"$TMP_ENV_FILE"
  else
    printf "%s\n" "$line" >>"$TMP_ENV_FILE"
  fi
done <".env.example"

mv "$TMP_ENV_FILE" ".env"
for required_key in POSTGRES_PASSWORD INTERNAL_API_SECRET EXECUTOR_TOKEN; do
  if ! grep -qE "^${required_key}=.+" ".env"; then
    echo "Errore: ${required_key} è vuota in .env" >&2
    exit 1
  fi
done
echo "Creato .env da .env.example con valori valorizzati"

mkdir -p data credentials config
chmod -R a+rwX data credentials config

if [[ "$WITH_OVERRIDE" -eq 1 ]]; then
  if [[ ! -f "docker-compose.override.yml" && -f "docker-compose.override.yml.example" ]]; then
    cp "docker-compose.override.yml.example" "docker-compose.override.yml"
    echo "Creato docker-compose.override.yml da esempio"
  fi
fi

if [[ "$NO_UP" -eq 1 ]]; then
  echo "Preparazione completata (NO_UP=1)."
  echo "Avvio manuale: docker compose up -d --build"
  exit 0
fi

if [[ "$NO_PULL" -eq 0 ]]; then
  docker compose pull
fi

UP_ARGS=(-d)
if [[ "$NO_BUILD" -eq 0 ]]; then
  UP_ARGS+=(--build)
fi

docker compose up "${UP_ARGS[@]}"

echo "Avvio completato."
echo "UI: ${BASE_URL_TO_SET}"
echo "Setup admin: ${BASE_URL_TO_SET}/auth/setup"
