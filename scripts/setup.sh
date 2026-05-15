#!/usr/bin/env bash
# IRA — First-time setup script
set -e

echo ""
echo "======================================"
echo "  IRA — Intelligent Responsive Assistant"
echo "  First-time Setup"
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
  echo ""
  echo "IMPORTANT: Open .env and add your API keys:"
  echo "  - OPENAI_API_KEY or ANTHROPIC_API_KEY (required for LLM)"
  echo "  - DEEPGRAM_API_KEY (for voice STT)"
  echo "  - ELEVENLABS_API_KEY (for IRA's voice)"
  echo "  - TAVILY_API_KEY (for web search)"
  echo ""
  echo "Then run: make up"
else
  echo "✓ .env already exists"
  echo "Run: make up"
fi
