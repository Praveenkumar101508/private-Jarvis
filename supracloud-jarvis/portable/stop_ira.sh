#!/usr/bin/env bash
# IRA Portable — stop the stack (Linux/macOS).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
ENV_FILE="${IRA_ENV_FILE:-$HERE/.env}"
COMPOSE_FILE="$ROOT/docker-compose.portable.yml"

[ -f "$COMPOSE_FILE" ] || { echo "ERROR: missing $COMPOSE_FILE" >&2; exit 1; }
echo ">> Stopping IRA portable stack"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" down
echo ">> Stopped. (Data in ./data, ./logs, ./config is preserved.)"
