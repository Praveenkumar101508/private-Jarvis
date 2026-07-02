# SupraCloud IRA — Architecture

IRA is a **local-first, single-owner personal AI assistant**. The current production shape
is the **native Ollama + Cortex era**: inference, memory, and reasoning all run on the
owner's machine; Docker is used only for the optional portable/test profiles and the
dormant cloud-scale path.

## System components

```
User (browser · PWA · voice)
        ↓
Next.js 14 frontend (supracloud-jarvis/frontend, port 3000)
        ↓ /api/v1/* · /auth/* · /health   (SSE for streaming)
FastAPI gateway (supracloud-jarvis/ira/main.py, port 8000)
        ↓
LangGraph pipeline (ira/agents/graph.py)
  retrieve memory → classify/route → owner gate → specialist agent → verify → store
        ↓                                   ↓
Model router (ira/reasoning/)         Cortex bridge (ira/cortex_bridge.py)
  local_fast / local_main /             localhost-only reasoning engine
  local_reasoning / local_coding /            ↓
  local_vision / memory_embedding      Ollama (qwen3:8b · qwen3:14b · qwen2.5vl)
        ↓
PostgreSQL + pgvector (memory, conversations, biometrics)   ·   Redis (cache, revocation, rate limits)
        ↓
Background workers (ira/worker/) — briefings, heartbeat, security monitor,
self-healing, reminders, backups, mobile push
```

| Component | Path | Role |
| --- | --- | --- |
| FastAPI gateway | `supracloud-jarvis/ira/main.py` + `api/routes/` (33 routers) | HTTP/SSE surface, auth, rate limiting |
| Agent graph | `ira/agents/graph.py` | LangGraph pipeline + 12 specialist agents |
| Model routing | `ira/reasoning/` | classify → pick local model tier → answer policy → verifier |
| Cortex bridge | `ira/cortex_bridge.py` | anti-corruption layer to the local reasoning engine (localhost-bound) |
| Memory | `ira/memory/` | pgvector store, BGE embeddings, reranker, life graph, decision journal |
| Research | `ira/research/` + `ira/channels/` | multi-round deep research over self-hosted SearXNG/Crawl4AI, RSS, GitHub, YouTube |
| Actions | `ira/actions/` | IMAP email triage, CalDAV calendar, notes, drafting — confirmation-gated |
| Voice | `ira/voice/` | wake word, Whisper STT, OmniVoice/Supertonic TTS, ECAPA voice biometrics |
| Workers | `ira/worker/` | 14 scheduled/background jobs (APScheduler) |
| Frontend | `supracloud-jarvis/frontend/` | Next.js 14 + Tailwind chat/voice UI |
| Mobile | `supracloud-jarvis/mobile/` | optional Expo PWA companion (off by default) |
| Portable profile | `supracloud-jarvis/portable/` | USB/self-contained profile with master password |

## Data flow (one text turn)

1. Browser POSTs to `/api/v1/chat/stream` with a JWT; response streams as SSE tokens.
2. `retrieve_memory` pulls top-ranked, capped, de-duplicated memories (pgvector cosine),
   labelled *reference-only* so stored text can never act as an instruction.
3. `classify` routes via keyword fast-path, then LLM fallback, to one of the specialist
   agents; the model router picks the right local tier for the task.
4. The owner/biometric gate blocks restricted domains for non-owner sessions.
5. The agent answers through the Cortex bridge → local Ollama; a rule-based verifier
   checks the draft (report-only) before it ships.
6. The interaction is stored and embedded asynchronously for future recall.

## Frontend / backend boundary

The frontend is a thin client: all intelligence lives behind `/api/v1/*`. Auth is JWT
(30-min access + 7-day refresh, jti revocation, optional TOTP); streaming is plain SSE so
any client (mobile PWA, scripts) can consume it. LiveKit/WebRTC voice is a legacy
transport kept behind `NEXT_PUBLIC_VOICE_TRANSPORT=livekit`; browser-native voice is the
default path.

## Local-first / privacy model

- All model roles resolve to **local Ollama models**; the Cortex reasoning engine must be
  on `127.0.0.1` (a non-local URL triggers loud startup sovereignty warnings).
- **External APIs are off by default**: `IRA_ALLOW_EXTERNAL_API=false`,
  `WEB_SEARCH_ENABLED=false`. Deep Intelligence Mode (frontier-model escalation) is a
  consent-gated *offer*, audited, and inert until wired and approved.
- `IRA_PRIVACY_MODE=local_only` suppresses even the offer.
- `DEV_MODE=true` (auth bypass) refuses to start on a non-local domain or a non-loopback
  bind host — enforced in `config.py`, tested in `tests/test_devmode_guard.py`.
- Every destructive or outbound action (send, delete, schedule) requires explicit human
  confirmation — no silent execution.

## Extension points

- **New agent**: add a module under `ira/agents/`, register it in `graph.py`, and add a
  route label; skills/personas live under `ira/skills/<name>/SKILL.md`.
- **New action**: implement under `ira/actions/` and gate it through the approval
  utilities in `ira/utils/approval.py` (see `tests/test_action_gating.py` for the contract).
- **New research channel**: subclass the base in `ira/channels/base.py`; all fetched
  content must pass input sanitization before reaching a model (adversarial tests
  enforce this).
- **Model profiles**: add/edit tiers in `ira/config/routing.yaml` or switch profiles via
  `IRA_MODEL_PROFILE` (`low_resource` / `balanced_local` / `strong_local`).
- **Legacy/dormant paths**: vLLM GPU stack and `future-scale/` (cloud) are kept as
  upgrade blueprints; `docker-compose.cloud.yml`/`docker-compose.test.yml` overlay a
  retired base compose file and are marked legacy in-file.
