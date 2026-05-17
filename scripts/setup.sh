#!/usr/bin/env bash
# IRA — First-time setup script
set -e

echo ""
echo "======================================"
echo "  IRA — Intelligent Responsive Assistant"
echo "  First-time Setup (Sovereign Mode)"
echo "======================================"
echo ""

# Check Docker
if ! command -v docker &>/dev/null; then
  echo "ERROR: Docker not found. Install Docker Desktop or Docker Engine first."
  exit 1
fi

# Check Docker Compose
if ! docker compose version &>/dev/null; then
  echo "ERROR: Docker Compose v2 not found."
  exit 1
fi

# Create .env
if [ ! -f .env ]; then
  cp .env.example .env
  echo "✓ Created .env from .env.example"
else
  echo "✓ .env already exists"
fi

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  IRA runs in SOVEREIGN MODE — 100% local, no API keys   ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "Before running 'make up', complete these steps:"
echo ""
echo "1. EDIT .env — set your Tailscale IPs:"
echo "   OLLAMA_BASE_URL=http://localhost:11434         # MacBook Air M1"
echo "   OLLAMA_HEAVY_URL=http://<shadow-pc-tailscale-ip>:11434"
echo "   DATABASE_URL=postgresql://ira:ira_pass@<shadow-pc-tailscale-ip>:5432/ira_db"
echo ""
echo "2. PULL Ollama models:"
echo "   MacBook Air M1:  ollama pull llama3.1:8b"
echo "   Shadow PC:       OLLAMA_HOST=0.0.0.0 ollama serve"
echo "                    ollama pull qwen2.5-coder:32b"
echo ""
echo "3. DOWNLOAD kokoro ONNX voice model (local TTS):"
echo "   mkdir -p backend/voice/models"
echo "   # Download kokoro-v0_19.onnx + voices.bin from:"
echo "   # https://github.com/thewh1teagle/kokoro-onnx/releases"
echo "   # Place both files in backend/voice/models/"
echo ""
echo "4. CONNECT Tailscale on both machines:"
echo "   curl -fsSL https://tailscale.com/install.sh | sh"
echo "   sudo tailscale up"
echo "   tailscale ip -4   # get Shadow PC IP for step 1"
echo ""
echo "5. START IRA:"
echo "   make up"
echo ""
echo "   API:      http://localhost:8000"
echo "   Frontend: http://localhost:3000"
echo "   API Docs: http://localhost:8000/docs"
echo ""
echo "Optional (cloud fallback):"
echo "   TAVILY_API_KEY=...    for web search"
echo "   TELEGRAM_BOT_TOKEN=... for notifications"
echo "   GOOGLE_CLIENT_ID=...   for calendar integration"
echo ""
