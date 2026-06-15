#!/usr/bin/env bash
# =============================================================================
# SupraCloud IRA — Health Verification Script
# Run after: docker compose up -d
#
# Checks every service and reports a clear pass/fail status.
# Exit code 0 = all healthy, 1 = one or more failures.
# =============================================================================

set -uo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

PASS=0; FAIL=0

ok()   { echo -e "  ${GREEN}✓${NC} $*"; ((PASS++)); }
fail() { echo -e "  ${RED}✗${NC} $*"; ((FAIL++)); }
info() { echo -e "  ${BLUE}→${NC} $*"; }
header() { echo -e "\n${BOLD}${BLUE}── $* ──${NC}"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

# Load env
if [[ -f ".env" ]]; then
    set -a; source .env; set +a
else
    echo -e "${RED}ERROR: .env not found. Run bash scripts/setup.sh first.${NC}"
    exit 1
fi

echo ""
echo -e "${BOLD}${BLUE}╔═══════════════════════════════════════╗${NC}"
echo -e "${BOLD}${BLUE}║   SupraCloud IRA — Health Check    ║${NC}"
echo -e "${BOLD}${BLUE}╚═══════════════════════════════════════╝${NC}"

# =============================================================================
# DOCKER CONTAINER STATUS
# =============================================================================
header "Container Status"

CONTAINERS=(
    "ira-postgres"
    "ira-redis"
    "ira-vllm-fast"
    "ira-vllm-deep"
    "ira-livekit"
    "ira-nginx"
    "ira-voice"
)

for container in "${CONTAINERS[@]}"; do
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' "${container}" 2>/dev/null || echo "not_found")
    RUNNING=$(docker inspect --format='{{.State.Running}}' "${container}" 2>/dev/null || echo "false")

    if [[ "${RUNNING}" == "true" ]]; then
        if [[ "${STATUS}" == "healthy" ]]; then
            ok "${container} — running & healthy"
        elif [[ "${STATUS}" == "starting" ]]; then
            info "${container} — running (health check starting...)"
        elif [[ "${STATUS}" == "unhealthy" ]]; then
            fail "${container} — running but UNHEALTHY"
        else
            ok "${container} — running (no healthcheck)"
        fi
    else
        fail "${container} — NOT running"
    fi
done

# =============================================================================
# POSTGRESQL
# =============================================================================
header "PostgreSQL"

if docker exec ira-postgres pg_isready -U "${POSTGRES_USER:-jarvis}" -d "${POSTGRES_DB:-jarvis_db}" &>/dev/null; then
    ok "PostgreSQL accepting connections"

    # Check pgvector extension
    EXT=$(docker exec ira-postgres psql -U "${POSTGRES_USER:-jarvis}" -d "${POSTGRES_DB:-jarvis_db}" -tAc "SELECT extname FROM pg_extension WHERE extname='vector';" 2>/dev/null)
    if [[ "${EXT}" == "vector" ]]; then
        ok "pgvector extension installed"
    else
        fail "pgvector extension NOT installed"
    fi

    # Check tables exist
    TABLES=$(docker exec ira-postgres psql -U "${POSTGRES_USER:-jarvis}" -d "${POSTGRES_DB:-jarvis_db}" -tAc "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null || echo "0")
    if [[ "${TABLES}" -ge 5 ]]; then
        ok "Schema initialized (${TABLES} tables)"
    else
        fail "Schema not initialized (only ${TABLES} tables found)"
    fi
else
    fail "PostgreSQL not accepting connections"
fi

# =============================================================================
# REDIS
# =============================================================================
header "Redis"

PONG=$(docker exec ira-redis redis-cli --no-auth-warning -a "${REDIS_PASSWORD}" ping 2>/dev/null || echo "")
if [[ "${PONG}" == "PONG" ]]; then
    ok "Redis responding to PING"
    MEM=$(docker exec ira-redis redis-cli --no-auth-warning -a "${REDIS_PASSWORD}" info memory 2>/dev/null | grep "used_memory_human" | cut -d: -f2 | tr -d '\r')
    ok "Redis memory in use: ${MEM}"
else
    fail "Redis not responding"
fi

# =============================================================================
# vLLM FAST PATH
# =============================================================================
header "vLLM Fast Path (Llama 3.1 8B)"

FAST_HEALTH=$(curl -sf "http://localhost:8001/health" 2>/dev/null || echo "")
if [[ "${FAST_HEALTH}" == *"ok"* ]] || curl -sf "http://localhost:8001/health" &>/dev/null; then
    ok "vLLM fast endpoint /health → OK"

    # Check model is loaded
    MODELS=$(curl -sf -H "Authorization: Bearer ${VLLM_API_KEY}" "http://localhost:8001/v1/models" 2>/dev/null || echo "")
    if [[ "${MODELS}" == *"llama-fast"* ]]; then
        ok "Model 'llama-fast' loaded"
    else
        fail "Model 'llama-fast' not yet available (still loading?)"
        info "Run: docker logs ira-vllm-fast --tail 20"
    fi

    # Quick inference test
    info "Running inference test on fast path..."
    RESPONSE=$(curl -sf -X POST \
        -H "Authorization: Bearer ${VLLM_API_KEY}" \
        -H "Content-Type: application/json" \
        -d '{"model":"llama-fast","messages":[{"role":"user","content":"Reply with exactly: IRA_ONLINE"}],"max_tokens":10,"temperature":0}' \
        "http://localhost:8001/v1/chat/completions" 2>/dev/null || echo "")

    if [[ "${RESPONSE}" == *"IRA_ONLINE"* ]] || [[ "${RESPONSE}" == *"content"* ]]; then
        ok "Fast path inference test PASSED"
    else
        fail "Fast path inference test FAILED (check logs)"
    fi
else
    fail "vLLM fast path not responding on :8001"
    info "Check: docker logs ira-vllm-fast --tail 30"
fi

# =============================================================================
# vLLM DEEP PATH
# =============================================================================
header "vLLM Deep Path (Qwen 2.5 14B)"

if curl -sf "http://localhost:8002/health" &>/dev/null; then
    ok "vLLM deep endpoint /health → OK"

    MODELS=$(curl -sf -H "Authorization: Bearer ${VLLM_API_KEY}" "http://localhost:8002/v1/models" 2>/dev/null || echo "")
    if [[ "${MODELS}" == *"qwen-deep"* ]]; then
        ok "Model 'qwen-deep' loaded"
    else
        fail "Model 'qwen-deep' not yet available (still loading?)"
        info "Run: docker logs ira-vllm-deep --tail 20"
    fi
else
    fail "vLLM deep path not responding on :8002"
    info "Check: docker logs ira-vllm-deep --tail 30"
fi

# =============================================================================
# LIVEKIT
# =============================================================================
header "LiveKit (Voice / WebRTC)"

if curl -sf "http://localhost:7880/" &>/dev/null; then
    ok "LiveKit server responding on :7880"
else
    fail "LiveKit not responding on :7880"
fi

# Check UDP port (basic socket check)
if nc -zu localhost 7882 2>/dev/null; then
    ok "LiveKit UDP port :7882 open"
else
    info "LiveKit UDP :7882 — cannot verify from localhost (expected for WebRTC)"
fi

# =============================================================================
# NGINX
# =============================================================================
header "Nginx (TLS Proxy)"

HTTP_CODE=$(curl -sk -o /dev/null -w "%{http_code}" "https://localhost/health" 2>/dev/null || echo "0")
if [[ "${HTTP_CODE}" == "200" ]]; then
    ok "Nginx HTTPS /health → 200"
elif [[ "${HTTP_CODE}" == "000" ]]; then
    fail "Nginx not responding on :443"
else
    info "Nginx HTTPS /health → ${HTTP_CODE} (may be redirect — check config)"
fi

HTTP_REDIRECT=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost/health" 2>/dev/null || echo "0")
if [[ "${HTTP_REDIRECT}" == "200" ]] || [[ "${HTTP_REDIRECT}" == "301" ]]; then
    ok "Nginx HTTP :80 responding (${HTTP_REDIRECT})"
else
    fail "Nginx HTTP :80 not responding"
fi

# =============================================================================
# GPU STATUS
# =============================================================================
header "GPU Status"

if command -v nvidia-smi &>/dev/null; then
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)
    GPU_UTIL=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader | head -1)
    MEM_USED=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader | head-1 2>/dev/null || nvidia-smi --query-gpu=memory.used --format=csv,noheader | head -1)
    MEM_TOTAL=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader | head -1)
    ok "${GPU_NAME}"
    ok "VRAM: ${MEM_USED} / ${MEM_TOTAL} used"
    ok "GPU utilization: ${GPU_UTIL}"
else
    fail "nvidia-smi not found"
fi

# =============================================================================
# SUMMARY
# =============================================================================
echo ""
echo -e "${BOLD}${BLUE}══════════════════════════════════════${NC}"
TOTAL=$((PASS + FAIL))
if [[ "${FAIL}" -eq 0 ]]; then
    echo -e "${BOLD}${GREEN}  ✓ All checks passed (${PASS}/${TOTAL})${NC}"
    echo -e "${GREEN}  SupraCloud IRA is ONLINE and healthy.${NC}"
    EXIT_CODE=0
else
    echo -e "${BOLD}${RED}  ✗ ${FAIL} check(s) failed (${PASS}/${TOTAL} passed)${NC}"
    echo -e "${YELLOW}  Review failures above and check docker logs.${NC}"
    EXIT_CODE=1
fi
echo -e "${BOLD}${BLUE}══════════════════════════════════════${NC}"
echo ""

exit ${EXIT_CODE}
