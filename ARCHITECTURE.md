# Architecture

## System Overview

```
User (browser/mobile)
        ↓ HTTPS
   nginx reverse proxy
        ↓
   /api/v1/*    /livekit/*    / (frontend)
        ↓             ↓             ↓
  ira-api        LiveKit       Next.js 14
  (FastAPI)       Server         (SSR)
        ↓             ↓
  LangGraph     ira-voice
  multi-agent     agent
    graph       (LiveKit
        ↓         Agents)
  vLLM fast/       ↓
   deep         Faster-Whisper
  (Qwen3)          STT
        ↓         Kokoro TTS
  PostgreSQL        ↓
  + pgvector    ECAPA-TDNN
        ↓        biometrics
  Redis
  (cache/pub-sub)
        ↓
  ira-worker
  (APScheduler)
```

## Services (docker-compose.yml)

| Service | Port | Purpose |
|---|---|---|
| `ira-api` | 8000 | FastAPI backend, LangGraph agents |
| `ira-worker` | — | APScheduler background jobs |
| `ira-voice` | — | LiveKit Agents voice pipeline |
| `ira-frontend` | 3000 | Next.js UI |
| `postgres` | 5432 | Primary data store + pgvector |
| `redis` | 6379 | Cache, pub/sub, rate limiting |
| `livekit` | 7880 | WebRTC voice server |
| `nginx` | 80/443 | Reverse proxy, TLS, rate limiting |
| `vllm-fast` | 8001 | Fast LLM (Qwen3-8B) |
| `vllm-deep` | 8002 | Deep LLM (Qwen3-14B) |

## Production Model Stack (2026)

| Tier | Local (RTX A4500 20GB) | Cloud (8×H100) |
|---|---|---|
| Fast | Qwen3-8B-AWQ (~7GB) | Qwen3-30B-A3B (MoE) |
| Deep | Qwen3-14B-AWQ (~12GB) | Qwen3-72B |
| Reasoning | Falls back to deep | DeepSeek-R1 671B |
| Vision | — (optional) | Qwen3-VL-72B |
| Embeddings | BGE-large-en-v1.5 (CPU) | BGE-large-en-v1.5 (CPU) |

## Agent Routing

Every chat request flows through:
1. `retrieve_memory` — fetch top-5 relevant past memories (pgvector cosine)
2. `classify` — keyword fast-path → LLM fallback router
3. `biometric_gate` — block restricted domains for non-owners
4. Specialist agent (one of 9)
5. `store_interaction` — persist message + async embedding

## Database Schema

Core tables: `conversations`, `messages`, `memory_embeddings` (pgvector), `agents`, `security_events`, `business_events`, `notifications`, `tasks`, `reminders`, `calendar_events`, `voice_profiles`, `biometric_audit`, `model_performance`

## External Integrations (Optional)

All external integrations are **opt-in** via `.env` variables:
- **Replicate**: Image gen (FLUX), video gen (Wan2.1), audio gen (MusicGen/Bark)
- **Apify**: LinkedIn/Indeed job board scraping
- **Cal.com**: Calendar sync and booking management
- **Telegram Bot API**: Push notifications
- **SMTP**: Email notifications
- **Twitter/X API v2**: Real-time social search
- **GitHub API**: Repository analysis for career tools
