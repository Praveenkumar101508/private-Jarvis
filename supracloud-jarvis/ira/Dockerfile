# =============================================================================
# SupraCloud IRA — Dockerfile  (v1.0.0 — Cloud-Ready Edition)
# Python 3.12 slim, multi-stage build
#
# Build args:
#   EMBEDDING_DEVICE  cpu (default) | cuda
#   HF_MODEL          BAAI/bge-large-en-v1.5 (default)
#   WORKERS           1 (default) — increase on cloud (uvicorn workers)
#
# Shadow PC (local dev):
#   docker build -t ira-api .
#
# Cloud (8×H100, high concurrency):
#   docker build --build-arg EMBEDDING_DEVICE=cuda --build-arg WORKERS=4 -t ira-api .
# =============================================================================

# ── Stage 1: Dependency builder ───────────────────────────────────────────────
FROM python:3.12-slim AS builder

ARG EMBEDDING_DEVICE=cpu

WORKDIR /build

# System deps for building Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install into a prefix so we can copy it cleanly to the runtime stage
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: Runtime image ────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ARG EMBEDDING_DEVICE=cpu
ARG HF_MODEL=BAAI/bge-large-en-v1.5
ARG WORKERS=1

WORKDIR /app

# Runtime system libs only (no build tools)
# libpq5 — PostgreSQL client, git — self-healing git operations
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for security — matches expected UID in most cloud environments
RUN useradd --create-home --shell /bin/bash --uid 1000 jarvis
USER jarvis
ENV PATH="/home/jarvis/.local/bin:${PATH}"
ENV EMBEDDING_DEVICE=${EMBEDDING_DEVICE}
ENV WORKERS=${WORKERS}

# Copy installed packages from builder
COPY --from=builder --chown=jarvis:jarvis /install /usr/local

# Copy application source
COPY --chown=jarvis:jarvis . /app

# Pre-download BGE embedding model at build time so container starts fast
# Set HF_HOME so it lands in the shared hf_cache volume mount point
ENV HF_HOME=/home/jarvis/.cache/huggingface
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${HF_MODEL}')" \
    || echo "[IRA] BGE model pre-download skipped — will download on first run"

# Install Playwright Chromium browser + OS dependencies.
# Fix #78: playwright package is already in requirements.txt (installed in
# stage 1) — only the browser binary and system deps need to be fetched here.
# Running pip install playwright again was doubling install time for no benefit.
USER root
RUN playwright install chromium --with-deps \
    && chown -R jarvis:jarvis /root/.cache/ms-playwright 2>/dev/null || true
USER jarvis

EXPOSE 8000

# Graceful startup: wait for postgres/redis, then start
HEALTHCHECK --interval=30s --timeout=10s --retries=10 --start-period=60s \
    CMD curl -sf http://localhost:8000/health || exit 1

# uvloop + uvicorn: fastest async event loop available for Python
# On cloud: set WORKERS=4 (or higher) via build arg or env override
CMD uvicorn main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers ${WORKERS} \
    --loop uvloop \
    --log-level info \
    --access-log
