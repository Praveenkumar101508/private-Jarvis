# =============================================================================
# SupraCloud Jarvis API — Dockerfile
# Python 3.12 slim, multi-stage build
# =============================================================================

# ── Stage 1: Dependency builder ───────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# System deps for building Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install into a prefix so we can copy it cleanly to the runtime stage
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: Runtime image ────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

WORKDIR /app

# Runtime system libs only (no build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for security
RUN useradd --create-home --shell /bin/bash jarvis
USER jarvis
ENV PATH="/home/jarvis/.local/bin:${PATH}"

# Copy installed packages from builder
COPY --from=builder --chown=jarvis:jarvis /install /usr/local

# Copy application source
COPY --chown=jarvis:jarvis . /app

# Pre-download BGE embedding model at build time so container starts fast
# This runs as jarvis user, caches to /home/jarvis/.cache/huggingface
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-large-en-v1.5')" \
    || echo "Model pre-download skipped — will download on first run"

# Install Playwright Chromium for the digital agent (browser_tools.py)
# Must run as root — switch back to jarvis afterward
USER root
RUN pip install --no-cache-dir playwright && playwright install chromium --with-deps
USER jarvis

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=5 --start-period=30s \
    CMD curl -sf http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--loop", "uvloop", "--log-level", "info"]
