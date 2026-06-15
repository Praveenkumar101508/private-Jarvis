#!/usr/bin/env bash
# =============================================================================
# SupraCloud IRA — One-Command Setup Script
# Run this ONCE before the first docker compose up.
#
# Usage: bash scripts/setup.sh
#
# What it does:
#   1. Checks prerequisites (Docker, NVIDIA, CUDA)
#   2. Creates .env from .env.example with generated secrets
#   3. Generates a self-signed TLS certificate for nginx
#   4. Sets correct file permissions
#   5. Pulls all Docker images
#   6. Prints next steps
# =============================================================================

set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC}  $*"; }
err()  { echo -e "${RED}✗ ERROR:${NC} $*" >&2; exit 1; }
info() { echo -e "${BLUE}→${NC} $*"; }
header() { echo -e "\n${BOLD}${BLUE}══════════════════════════════════════${NC}"; echo -e "${BOLD} $* ${NC}"; echo -e "${BOLD}${BLUE}══════════════════════════════════════${NC}\n"; }

# ── Run from repo root ─────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

header "SupraCloud IRA — Setup"

# =============================================================================
# 1. PREREQUISITES CHECK
# =============================================================================
header "Step 1: Prerequisites"

# Docker
command -v docker &>/dev/null || err "Docker is not installed. Install from https://docs.docker.com/engine/install/"
DOCKER_VERSION=$(docker --version | grep -oP '\d+\.\d+' | head -1)
ok "Docker ${DOCKER_VERSION}"

# Docker Compose v2
docker compose version &>/dev/null || err "Docker Compose v2 not found. Run: sudo apt install docker-compose-plugin"
ok "Docker Compose v2"

# NVIDIA Driver
if command -v nvidia-smi &>/dev/null; then
    DRIVER_VERSION=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1)
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
    GPU_MEM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader 2>/dev/null | head -1)
    ok "NVIDIA Driver ${DRIVER_VERSION} — ${GPU_NAME} (${GPU_MEM})"
else
    err "nvidia-smi not found. Install NVIDIA drivers: https://docs.nvidia.com/datacenter/tesla/driver-installation-guide/"
fi

# nvidia-container-toolkit
if docker info 2>/dev/null | grep -q "nvidia"; then
    ok "nvidia-container-toolkit is configured"
else
    warn "nvidia-container-toolkit may not be installed or configured."
    warn "Install with: sudo apt install nvidia-container-toolkit && sudo systemctl restart docker"
    warn "Continuing — vLLM containers will fail without it."
fi

# openssl (for cert generation)
command -v openssl &>/dev/null || err "openssl not found. Install with: sudo apt install openssl"
ok "openssl"

# =============================================================================
# 2. ENVIRONMENT FILE
# =============================================================================
header "Step 2: Environment Configuration"

if [[ -f ".env" ]]; then
    warn ".env already exists — skipping creation. Edit it manually if needed."
else
    cp .env.example .env

    # Auto-generate secrets
    VLLM_KEY=$(openssl rand -hex 32)
    IRA_SECRET=$(openssl rand -hex 32)
    LIVEKIT_KEY=$(openssl rand -hex 16)
    LIVEKIT_SECRET=$(openssl rand -hex 32)

    # Prompt for required secrets
    echo ""
    echo -e "${BOLD}Please provide the following values:${NC}"
    echo ""

    read -rsp "PostgreSQL password: " PG_PASS; echo ""
    [[ -z "${PG_PASS}" ]] && err "PostgreSQL password cannot be empty."

    read -rsp "Redis password: " REDIS_PASS; echo ""
    [[ -z "${REDIS_PASS}" ]] && err "Redis password cannot be empty."

    read -rp "HuggingFace token (from https://huggingface.co/settings/tokens): " HF_TOKEN; echo ""
    [[ -z "${HF_TOKEN}" ]] && warn "HF_TOKEN is empty — required for Llama 3.1 (gated model). Set it in .env before starting."

    read -rp "Your domain (or IP, e.g. 192.168.1.100 or jarvis.yourdomain.com): " DOMAIN; echo ""
    DOMAIN="${DOMAIN:-ira.local}"

    # Patch .env with generated + user-provided values
    sed -i "s|CHANGE_ME_strong_password_here|${PG_PASS}|g"           .env
    sed -i "s|CHANGE_ME_redis_password_here|${REDIS_PASS}|g"         .env
    sed -i "s|CHANGE_ME_generate_with_openssl_rand_hex_32|${IRA_SECRET}|g" .env
    sed -i "s|CHANGE_ME_livekit_api_key|${LIVEKIT_KEY}|g"            .env
    sed -i "s|CHANGE_ME_livekit_api_secret|${LIVEKIT_SECRET}|g"      .env
    sed -i "s|hf_CHANGE_ME|${HF_TOKEN}|g"                            .env
    sed -i "s|VLLM_API_KEY=.*|VLLM_API_KEY=${VLLM_KEY}|g"            .env
    sed -i "s|IRA_DOMAIN=.*|JARVIS_DOMAIN=${DOMAIN}|g"            .env
    # Second occurrence of the jarvis secret (JARVIS_SECRET_KEY line)
    sed -i "s|IRA_SECRET_KEY=.*|IRA_SECRET_KEY=${IRA_SECRET}|g" .env

    chmod 600 .env
    ok ".env created and secrets auto-generated."
    echo ""
    echo -e "  ${YELLOW}SAVE these values somewhere safe:${NC}"
    echo -e "  vLLM API Key : ${BOLD}${VLLM_KEY}${NC}"
    echo -e "  LiveKit Key  : ${BOLD}${LIVEKIT_KEY}${NC}"
    echo -e "  LiveKit Secret: ${BOLD}${LIVEKIT_SECRET}${NC}"
fi

# =============================================================================
# 3. TLS CERTIFICATE (self-signed for Phase 1)
# =============================================================================
header "Step 3: TLS Certificate"

if [[ -f "nginx/certs/ira.crt" && -f "nginx/certs/ira.key" ]]; then
    ok "TLS certs already exist — skipping."
else
    mkdir -p nginx/certs

    # Read domain from .env for SAN
    DOMAIN=$(grep "IRA_DOMAIN=" .env | cut -d= -f2 | tr -d '"' || echo "ira.local")

    openssl req -x509 -nodes -days 3650 \
        -newkey rsa:4096 \
        -keyout nginx/certs/ira.key \
        -out nginx/certs/ira.crt \
        -subj "/C=US/ST=Private/L=Private/O=SupraCloud IRA/CN=${DOMAIN}" \
        -addext "subjectAltName=DNS:${DOMAIN},DNS:localhost,IP:127.0.0.1" \
        2>/dev/null

    chmod 600 nginx/certs/ira.key
    chmod 644 nginx/certs/ira.crt
    ok "Self-signed TLS cert generated for ${DOMAIN} (valid 10 years)."
    warn "Replace with a real cert from Let's Encrypt for production."
fi

# =============================================================================
# 4. FILE PERMISSIONS
# =============================================================================
header "Step 4: Permissions"

chmod +x scripts/*.sh
chmod 600 .env 2>/dev/null || true
chmod 644 nginx/nginx.conf livekit/livekit.yaml postgres/init.sql
ok "File permissions set."

# =============================================================================
# 5. PULL DOCKER IMAGES
# =============================================================================
header "Step 5: Pull Docker Images"
info "This will download ~15GB+ of images. Grab a coffee."
echo ""

docker compose pull --quiet && ok "All images pulled successfully."

# =============================================================================
# 6. HuggingFace MODEL NOTE
# =============================================================================
header "Step 6: Model Download Info"

echo -e "${YELLOW}Models will be downloaded automatically on first start:${NC}"
echo ""
echo -e "  Fast Path: ${BOLD}hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4${NC}"
echo -e "  Deep Path: ${BOLD}Qwen/Qwen2.5-14B-Instruct-AWQ${NC}"
echo ""
echo -e "  Total download: ~${BOLD}15GB${NC}"
echo -e "  ${YELLOW}First start will take 5–20 minutes.${NC} Subsequent starts use the cache."
echo ""
warn "Llama 3.1 is a gated model. You must:"
echo "   1. Accept the license at: https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct"
echo "   2. Set HF_TOKEN in .env with a token that has access."

# =============================================================================
# DONE — NEXT STEPS
# =============================================================================
header "Setup Complete"

echo -e "Start Jarvis with:"
echo ""
echo -e "  ${BOLD}docker compose up -d${NC}"
echo ""
echo -e "Then verify everything is healthy:"
echo ""
echo -e "  ${BOLD}bash scripts/verify.sh${NC}"
echo ""
echo -e "Monitor startup logs:"
echo ""
echo -e "  ${BOLD}docker compose logs -f${NC}"
echo ""
echo -e "${GREEN}${BOLD}SupraCloud IRA is ready to be awakened.${NC}"
