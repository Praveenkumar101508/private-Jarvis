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

# Guard: abort early if executed with sh instead of bash (bash-isms used below)
if [ -z "${BASH_VERSION:-}" ]; then
    echo "ERROR: This script requires bash. Run: bash scripts/setup.sh" >&2
    exit 1
fi

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
# 1b. SOPS / AGE SECRETS SETUP (optional — skip if already initialised)
# =============================================================================
header "Step 1b: Secrets Setup (sops + age)"

if command -v sops &>/dev/null && [[ -f "${HOME}/.config/sops/age/keys.txt" ]]; then
    ok "sops and age key already configured — skipping init-secrets.sh"
else
    info "Running init-secrets.sh to set up sops + age encryption..."
    bash "${SCRIPT_DIR}/init-secrets.sh" || warn "init-secrets.sh reported an issue — continuing setup. Run it manually later."
fi

# =============================================================================
# 2. ENVIRONMENT FILE
# =============================================================================
header "Step 2: Environment Configuration"

if [[ -f ".env" ]]; then
    warn ".env already exists — skipping creation. Edit it manually if needed."
else
    cp .env.example .env

    # Auto-generate secrets — each one is unique
    VLLM_KEY=$(openssl rand -hex 32)
    IRA_SECRET=$(openssl rand -hex 32)
    # Fix P2: voice service token must be a JWT signed with IRA_SECRET_KEY (sub=ira-voice),
    # not a random hex string, or the API rejects it with 401. Expires in 10 years.
    VOICE_TOKEN=$(python3 -c "
import sys
try:
    from jose import jwt
    import datetime
    secret = '${IRA_SECRET}'
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3650)
    token = jwt.encode({'sub': 'ira-voice', 'exp': expire}, secret, algorithm='HS256')
    print(token)
except ImportError:
    # jose not available during setup — use a placeholder; run setup again after install
    print('REPLACE_WITH_JWT_AFTER_INSTALL')
    sys.exit(0)
")
    WEBHOOK_SECRET_VAL=$(openssl rand -hex 32)
    LIVEKIT_KEY=$(openssl rand -hex 16)
    LIVEKIT_SECRET=$(openssl rand -hex 32)

    # Prompt for required secrets
    echo ""
    echo -e "${BOLD}Please provide the following values:${NC}"
    echo ""

    # Suppress trace mode for all secret prompts so passwords never appear in logs
    { set +x; } 2>/dev/null
    read -rsp "PostgreSQL password: " PG_PASS; echo ""
    [[ -z "${PG_PASS}" ]] && err "PostgreSQL password cannot be empty."

    read -rsp "Admin web UI password (for IRA dashboard login): " ADMIN_PASS; echo ""
    [[ -z "${ADMIN_PASS}" ]] && err "Admin password cannot be empty."

    read -rsp "Redis password: " REDIS_PASS; echo ""
    [[ -z "${REDIS_PASS}" ]] && err "Redis password cannot be empty."

    read -rsp "HuggingFace token (from https://huggingface.co/settings/tokens): " HF_TOKEN; echo ""
    [[ -z "${HF_TOKEN}" ]] && warn "HF_TOKEN is empty — required for gated HuggingFace models. Set it in .env before starting."

    read -rp "Your domain (or IP, e.g. 192.168.1.100 or jarvis.yourdomain.com): " DOMAIN; echo ""
    DOMAIN="${DOMAIN:-ira.local}"

    # Patch .env with generated + user-provided values
    # Use field-specific patterns so POSTGRES_PASSWORD and IRA_ADMIN_PASSWORD
    # are set independently (they shared the same placeholder in .env.example).
    # Use Python for safe substitution — avoids sed breaking on passwords with special chars
    PG_PASS="$PG_PASS" \
    ADMIN_PASS="$ADMIN_PASS" \
    REDIS_PASS="$REDIS_PASS" \
    VLLM_KEY="$VLLM_KEY" \
    IRA_SECRET="$IRA_SECRET" \
    VOICE_TOKEN="$VOICE_TOKEN" \
    WEBHOOK_SECRET_VAL="$WEBHOOK_SECRET_VAL" \
    LIVEKIT_KEY="$LIVEKIT_KEY" \
    LIVEKIT_SECRET="$LIVEKIT_SECRET" \
    HF_TOKEN="$HF_TOKEN" \
    DOMAIN="$DOMAIN" \
    python3 - <<'PYEOF'
import re, os

with open('.env', 'r') as f:
    content = f.read()

replacements = {
    r'^POSTGRES_PASSWORD=CHANGE_ME_strong_password_here':   'POSTGRES_PASSWORD=' + os.environ['PG_PASS'],
    r'^IRA_ADMIN_PASSWORD=CHANGE_ME_strong_password_here':  'IRA_ADMIN_PASSWORD=' + os.environ['ADMIN_PASS'],
    r'^REDIS_PASSWORD=CHANGE_ME_redis_password_here':        'REDIS_PASSWORD=' + os.environ['REDIS_PASS'],
    r'^VLLM_API_KEY=.*':                                     'VLLM_API_KEY=' + os.environ['VLLM_KEY'],
    r'^IRA_SECRET_KEY=.*':                                   'IRA_SECRET_KEY=' + os.environ['IRA_SECRET'],
    r'^IRA_VOICE_API_TOKEN=.*':                              'IRA_VOICE_API_TOKEN=' + os.environ['VOICE_TOKEN'],
    r'^WEBHOOK_SECRET=.*':                                   'WEBHOOK_SECRET=' + os.environ['WEBHOOK_SECRET_VAL'],
    r'^LIVEKIT_API_KEY=.*':                                  'LIVEKIT_API_KEY=' + os.environ['LIVEKIT_KEY'],
    r'^LIVEKIT_API_SECRET=.*':                               'LIVEKIT_API_SECRET=' + os.environ['LIVEKIT_SECRET'],
    r'^HF_TOKEN=.*':                                         'HF_TOKEN=' + os.environ['HF_TOKEN'],
    r'^IRA_DOMAIN=.*':                                       'IRA_DOMAIN=' + os.environ['DOMAIN'],
}

for pattern, replacement in replacements.items():
    content = re.sub(pattern, replacement, content, flags=re.MULTILINE)

with open('.env', 'w') as f:
    f.write(content)
print("ok")
PYEOF

    chmod 600 .env
    ok ".env created and secrets auto-generated."

    # Offer to encrypt .env with sops if age key is available
    if command -v sops &>/dev/null && [[ -f "${HOME}/.config/sops/age/keys.txt" ]]; then
        info "Encrypting .env with sops (add .env.enc to git instead of .env)..."
        SOPS_AGE_KEY_FILE="${HOME}/.config/sops/age/keys.txt" \
            sops --encrypt .env > .env.enc && ok "Created .env.enc (git-safe encrypted copy)" \
            || warn "sops encrypt failed — .env.enc not created. Commit .env.enc manually later."
    fi
    echo ""
    # Suppress trace mode so secrets don't appear in set -x output
    { set +x; } 2>/dev/null
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
echo -e "  Fast Path: ${BOLD}Qwen/Qwen3-8B${NC}  (or Qwen3-30B-A3B on cloud)"
echo -e "  Deep Path: ${BOLD}Qwen/Qwen3-14B${NC} (or Qwen3-72B on cloud)"
echo ""
echo -e "  Total download: ~${BOLD}15GB${NC}"
echo -e "  ${YELLOW}First start will take 5–20 minutes.${NC} Subsequent starts use the cache."
echo ""
info "If using gated HuggingFace models, set HF_TOKEN in .env before starting."

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
