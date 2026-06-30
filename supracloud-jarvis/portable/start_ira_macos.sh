#!/usr/bin/env bash
# IRA Portable — one-command start (macOS).
# Flow: check deps -> load demo.env -> verify master password -> start services ->
#       poll /health -> open browser on success. Every failure prints a clear reason.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
ENV_FILE="${IRA_ENV_FILE:-$HERE/.env}"
API_BASE="${IRA_API_BASE:-http://127.0.0.1:8000}"
FRONTEND_URL="${IRA_FRONTEND_URL:-http://localhost:3000}"
COMPOSE_FILE="$ROOT/docker-compose.portable.yml"

fail() { echo "ERROR: $*" >&2; exit 1; }
info() { echo ">> $*"; }

# 1. Dependencies
command -v python3 >/dev/null 2>&1 || fail "python3 is required."
command -v docker  >/dev/null 2>&1 || fail "docker is required (Docker Desktop must be running)."
docker compose version >/dev/null 2>&1 || fail "docker compose v2 is required."

# 2. Environment
[ -f "$ENV_FILE" ] || fail "missing env file: $ENV_FILE  (copy demo.env.example to .env and edit secrets)."
info "Loading $ENV_FILE"
set -a; # shellcheck disable=SC1090
source "$ENV_FILE"; set +a

# 3. Master password (refuses to continue without it)
info "Verifying master password"
python3 "$HERE/verify_master_password.py" --config-dir "${IRA_CONFIG_DIR:-$HERE/config}" \
    || fail "master password verification failed — not starting."

# 4. Services
[ -f "$COMPOSE_FILE" ] || fail "missing $COMPOSE_FILE (run from a complete IRA-Portable bundle)."
info "Starting core services (Postgres+pgvector, Redis, IRA API, frontend, local LLM)"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d \
    || fail "docker compose failed to start the stack."

# 5. Health gate
info "Waiting for IRA to become healthy ..."
if python3 "$HERE/health_check.py" --base-url "$API_BASE" --timeout "${IRA_READY_TIMEOUT:-120}"; then
    info "Opening $FRONTEND_URL"
    open "$FRONTEND_URL" >/dev/null 2>&1 || info "Open $FRONTEND_URL in your browser."
    info "IRA is up."
else
    fail "IRA did not become healthy. Check: docker compose -f \"$COMPOSE_FILE\" logs"
fi
