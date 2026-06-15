# =============================================================================
# IRA Voice Agent — Dockerfile
# Runs: Faster-Whisper STT + Kokoro TTS + LiveKit Agents worker
# All inference on CPU — preserves 20GB VRAM for LLM endpoints
# =============================================================================

FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libsndfile1-dev \
    portaudio19-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY voice/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Runtime ───────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    libportaudio2 \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash ira
USER ira
ENV PATH="/home/ira/.local/bin:${PATH}"

COPY --from=builder --chown=ira:ira /install /usr/local
COPY --chown=ira:ira . /app

# Pre-download Whisper large-v3 at build time (~1.5GB) so startup is instant
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('large-v3', device='cpu', compute_type='int8')" \
    || echo "Whisper pre-download skipped — will download on first run"

# Pre-download Kokoro ONNX model + voices
RUN python -c "from kokoro_onnx import Kokoro; Kokoro('kokoro-v0_19.onnx', 'voices.bin')" \
    || echo "Kokoro pre-download skipped — will download on first run"

HEALTHCHECK --interval=30s --timeout=10s --retries=5 --start-period=60s \
    CMD python -c "import faster_whisper; import kokoro_onnx; print('ok')" || exit 1

# Voice agent entrypoint
CMD ["python", "-m", "voice.agent"]
