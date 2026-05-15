# IRA — Intelligent Responsive Assistant

> A warm, multilingual AI assistant with an Indian female persona. She listens, remembers, and acts — in any Indian language.

## Features

| Phase | Feature | Status |
|-------|---------|--------|
| 1 | FastAPI backend + PostgreSQL + Redis | ✅ |
| 2 | LangGraph agent (intent → search → memory → respond) | ✅ |
| 3 | Voice layer — LiveKit + STT (Deepgram/Whisper) + TTS (ElevenLabs/Azure) | ✅ |
| 4 | Proactive worker — morning briefings, reminders, Telegram notifications | ✅ |
| + | SupraCloud website (subfolder) | ✅ |

## Architecture

```
private-Jarvis/
├── backend/                   # FastAPI + LangGraph agents
│   ├── agents/                # Phase 2: LangGraph graph + nodes + tools
│   ├── voice/                 # Phase 3: LiveKit agent, STT, TTS
│   ├── workers/               # Phase 4: Proactive worker (APScheduler)
│   ├── memory/                # Redis short-term + ChromaDB long-term
│   ├── persona/               # IRA personality, prompts, multilingual greetings
│   ├── routers/               # FastAPI routes (chat, voice, auth, health)
│   └── db/                    # PostgreSQL init.sql
├── frontend/                  # Next.js 14 chat UI (TypeScript + Tailwind)
├── livekit/                   # LiveKit server config
├── nginx/                     # Reverse proxy config
├── redis/                     # Redis config
├── supracloud-website/        # SupraCloud website (see below)
├── scripts/                   # Setup helpers
├── docker-compose.yml
├── .env.example
└── Makefile
```

## Quick Start

### 1. Clone and setup
```bash
git clone https://github.com/Praveenkumar101508/private-Jarvis.git
cd private-Jarvis
cp .env.example .env
nano .env   # Add your API keys
```

### 2. Required API keys (minimum)
```bash
OPENAI_API_KEY=sk-...          # OR ANTHROPIC_API_KEY / GROQ_API_KEY
DEEPGRAM_API_KEY=...           # Voice STT
ELEVENLABS_API_KEY=...         # IRA's warm Indian voice
TAVILY_API_KEY=...             # Web search
```

### 3. Run everything
```bash
docker compose up -d
docker compose logs backend -f   # Watch startup
```

| Service | URL |
|---------|-----|
| IRA Chat UI | http://localhost:3000 |
| IRA API | http://localhost:8000 |
| API Docs (Swagger) | http://localhost:8000/docs |
| SupraCloud Website | http://localhost:3001 |

## SupraCloud Website

The `supracloud-website/` folder is a placeholder. To merge in the actual website:

```bash
make pull-supracloud
```

## Voice

IRA defaults to ElevenLabs warm Indian female voice. To switch to Azure Neural TTS:
```bash
TTS_PROVIDER=azure
AZURE_TTS_KEY=your-key
AZURE_TTS_VOICE=en-IN-NeerjaNeural
```

## Multilingual Support

IRA auto-detects language and responds in the same language:
English, हिंदी, తెలుగు, தமிழ், ಕನ್ನಡ, മലയാളം, मराठी, বাংলা, ગુજરાતી, ਪੰਜਾਬੀ

## LLM Providers

```bash
LLM_PROVIDER=openai       # gpt-4o (default)
LLM_PROVIDER=anthropic    # claude-sonnet-4-6
LLM_PROVIDER=groq         # llama-3.3-70b (fast, free tier)
LLM_PROVIDER=ollama       # local models (no API cost)
```

## RunPod

Expose these ports in your RunPod pod settings:
- `3000` → IRA Frontend
- `8000` → IRA API
- `7880` → LiveKit voice
- `3001` → SupraCloud website

---

Built with care — IRA: Intelligent, Responsive, and always there for you.
