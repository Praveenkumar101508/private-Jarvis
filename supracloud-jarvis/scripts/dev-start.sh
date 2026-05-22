#!/usr/bin/env bash
# dev-start.sh — one-command IRA dev environment for Shadow PC / WSL2
# Starts only: postgres, redis, ira-api, frontend (skips vLLM, livekit, ira-worker)
# Requires: Docker, docker compose, Ollama running on Windows host

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_DIR/.env"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()    { echo -e "${CYAN}[IRA-DEV]${NC} $*"; }
success() { echo -e "${GREEN}[IRA-DEV]${NC} $*"; }
warn()    { echo -e "${YELLOW}[IRA-DEV]${NC} $*"; }
error()   { echo -e "${RED}[IRA-DEV]${NC} $*" >&2; }

# ── Ollama check ──────────────────────────────────────────────────────────────
check_ollama() {
  local ollama_url="${OLLAMA_BASE_URL:-http://host.docker.internal:11434}"
  # From WSL2/host itself, check on localhost too
  local check_url="${ollama_url/host.docker.internal/localhost}"
  if curl -sf "${check_url}/api/tags" > /dev/null 2>&1; then
    success "Ollama is running at ${check_url}"
    return 0
  elif curl -sf "${ollama_url}/api/tags" > /dev/null 2>&1; then
    success "Ollama is running at ${ollama_url}"
    return 0
  else
    error "Ollama not detected at ${check_url} or ${ollama_url}"
    error "Start Ollama on your Windows host:  ollama serve"
    exit 1
  fi
}

# ── Pull Ollama model if missing ───────────────────────────────────────────────
ensure_model() {
  local model="${DEV_MODEL:-llama3.2}"
  local check_url="${OLLAMA_BASE_URL:-http://localhost:11434}"
  check_url="${check_url/host.docker.internal/localhost}"

  info "Checking for model: ${model}"
  local tags
  tags=$(curl -sf "${check_url}/api/tags" 2>/dev/null || echo '{"models":[]}')
  if echo "$tags" | grep -q "\"${model}\""; then
    success "Model '${model}' already present"
  else
    warn "Model '${model}' not found — pulling (this may take a while)…"
    if command -v ollama &>/dev/null; then
      ollama pull "$model"
    else
      curl -sf -X POST "${check_url}/api/pull" \
        -H "Content-Type: application/json" \
        -d "{\"name\": \"${model}\"}" | \
        grep -o '"status":"[^"]*"' | tail -1 || true
    fi
    success "Model '${model}' ready"
  fi
}

# ── .env setup ────────────────────────────────────────────────────────────────
setup_env() {
  if [[ ! -f "$ENV_FILE" ]]; then
    warn ".env not found — copying from .env.example"
    cp "$PROJECT_DIR/.env.example" "$ENV_FILE"
    warn "Edit $ENV_FILE and fill in secrets before running in production."
  fi

  # Inject DEV_MODE overrides without touching the file permanently
  # (export into the current shell; docker compose picks them up)
  export DEV_MODE=true
  export OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://host.docker.internal:11434/v1}"
  export DEV_MODEL="${DEV_MODEL:-llama3.2}"

  # Ensure dummy secrets exist so the API starts (not used in dev)
  export VLLM_API_KEY="${VLLM_API_KEY:-dev-not-used}"
  export VLLM_FAST_URL="${VLLM_FAST_URL:-http://localhost:8000/v1}"
  export VLLM_DEEP_URL="${VLLM_DEEP_URL:-http://localhost:8001/v1}"

  success "DEV_MODE=true — auth and biometrics bypassed, LLM → Ollama"
}

# ── Docker compose helpers ────────────────────────────────────────────────────
DEV_SERVICES="postgres redis ira-api"

compose() {
  docker compose -f "$PROJECT_DIR/docker-compose.yml" \
    --env-file "$ENV_FILE" \
    "$@"
}

start_services() {
  info "Starting dev services: ${DEV_SERVICES}"
  compose up -d --build $DEV_SERVICES
}

wait_api() {
  info "Waiting for ira-api to be healthy…"
  local attempts=0
  until curl -sf http://localhost:8000/health > /dev/null 2>&1; do
    attempts=$((attempts + 1))
    if [[ $attempts -ge 30 ]]; then
      error "ira-api did not become healthy after 60s"
      compose logs --tail=40 ira-api
      exit 1
    fi
    sleep 2
  done
  success "ira-api is healthy"
}

start_frontend_dev() {
  local fe_dir="$PROJECT_DIR/frontend"
  if [[ -f "$fe_dir/package.json" ]]; then
    info "Starting Next.js dev server in background…"
    cd "$fe_dir"
    NEXT_PUBLIC_LIVEKIT_URL="${LIVEKIT_PUBLIC_URL:-ws://localhost:7880}" \
      npm run dev > /tmp/ira-frontend-dev.log 2>&1 &
    FRONTEND_PID=$!
    info "Frontend PID=${FRONTEND_PID} — logs: /tmp/ira-frontend-dev.log"
    cd - > /dev/null
  else
    warn "Frontend not found at ${fe_dir} — run 'npm run dev' manually"
  fi
}

print_urls() {
  echo ""
  echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${GREEN}  IRA Dev Environment Ready${NC}"
  echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "  Frontend  →  ${CYAN}http://localhost:3000${NC}"
  echo -e "  API       →  ${CYAN}http://localhost:8000${NC}"
  echo -e "  API Docs  →  ${CYAN}http://localhost:8000/docs${NC}"
  echo -e "  Model     →  ${CYAN}${DEV_MODEL}${NC} via Ollama"
  echo -e "  Auth      →  any username / any password (DEV_MODE=true)"
  echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo ""
  echo -e "  API logs:  ${YELLOW}docker compose logs -f ira-api${NC}"
  echo -e "  Stop DB/Redis/API: ${YELLOW}docker compose stop ${DEV_SERVICES}${NC}"
  echo -e "  Stop frontend:     ${YELLOW}kill \$FRONTEND_PID${NC}  (or Ctrl+C in its terminal)"
  echo -e "  Stop everything:   ${YELLOW}docker compose down${NC}"
  echo ""
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
  echo ""
  info "IRA Dev Start — Shadow PC / WSL2"
  echo ""

  setup_env
  check_ollama
  ensure_model
  start_services
  wait_api
  start_frontend_dev
  print_urls
}

main "$@"
