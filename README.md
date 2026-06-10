<div align="center">

# 🤖 SupraCloud IRA

### *Intelligent Responsive Assistant — Private Sovereign AI*

<br/>

[![Built by Praveenkumar](https://img.shields.io/badge/Built%20by-Praveenkumar-6366f1?style=for-the-badge&logo=github&logoColor=white)](https://github.com/Praveenkumar101508)
[![Python](https://img.shields.io/badge/Python-3.11-3776ab?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115.5-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2.73-ff6b35?style=for-the-badge)](https://langchain-ai.github.io/langgraph/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ed?style=for-the-badge&logo=docker&logoColor=white)](https://docker.com)
[![License](https://img.shields.io/badge/License-Private-red?style=for-the-badge)](.)

<br/>

> **IRA runs entirely on your own hardware.**
> No data leaves your server. No subscriptions. No cloud vendor lock-in.
> Your AI. Your rules. Forever.

<br/>

```
 ██╗██████╗  █████╗
 ██║██╔══██╗██╔══██╗
 ██║██████╔╝███████║
 ██║██╔══██╗██╔══██║
 ██║██║  ██║██║  ██║
 ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝   v1.0.0 · Private Sovereign AI
```

</div>

---

## 📋 Table of Contents

| | |
|---|---|
| [⚡ Quick Start](#-quick-start) | Get IRA running in 4 commands |
| [✨ Features](#-feature-status) | Everything IRA can do |
| [🏗️ Architecture](#-architecture) | How it all fits together |
| [🎙️ Voice Interface](#-voice-interface) | Biometric voice auth + TTS |
| [🔒 Security](#-security-architecture) | Zero-trust defence layers |
| [📖 Usage Guide](#-feature-usage-guide) | Chat modes, commands, examples |
| [🌐 API Reference](#-api-reference-key-endpoints) | All HTTP endpoints |
| [⚙️ Configuration](#-environment-variables) | .env reference |
| [📁 Project Structure](#-project-structure) | Every file explained |

---

## ✨ Feature Status

<div align="center">

| Feature | Status | Notes |
|:--------|:------:|:------|
| 💬 Chat with memory + RAG | ✅ **Production** | Streaming · Think Mode · Expert Mode |
| 📄 Document creation (PDF/Word/Excel/PPT) | ✅ **Production** | From chat prompt |
| 📎 Document upload + analysis | ✅ **Production** | PDF · DOCX · TXT |
| ⚙️ Engineer Mode (code diffs) | ✅ **Production** | 4-step workflow |
| 🔍 Web search + DeepSearch | ✅ **Production** | DuckDuckGo + X/Twitter |
| 🖼️ Image generation | ✅ **Production** | Replicate API or SD WebUI |
| 👁️ Vision / image analysis | ✅ **Production** | Requires vLLM vision endpoint |
| 🛡️ Security monitoring | ✅ **Production** | nginx log analysis · SSH brute-force |
| 💾 Daily backups | ✅ **Production** | pg_dump · 7-day retention |
| 📰 Morning/evening briefings | ✅ **Production** | Telegram or email |
| ✅ Task + reminder management | ✅ **Production** | APScheduler delivery |
| 🏛️ Architect Evolution mode | ✅ **Production** | 5-agent debate → auto git commit |
| 💼 Career tools (resume, job scrape) | ✅ **Production** | Requires Apify API token |
| 🗣️ Voice interface | ⚠️ **Beta** | English · see Voice section |
| 🧬 Biometric voice auth | ⚠️ **Beta** | Requires enrolment |
| 🎬 Video generation | 🔧 **Requires Replicate** | External API |
| 🎵 Audio/music generation | 🔧 **Requires Replicate** | External API |
| 🌏 Multilingual voice | 🔧 **Experimental** | Indic → English TTS (known limitation) |
| 🖥️ Computer use (Playwright) | 🔧 **Experimental** | SSRF protections required |

</div>

---

## 🚀 What IRA Can Do

<div align="center">

| Capability | Description |
|:-----------|:------------|
| 🌐 **Multi-language Chat** | English · Hindi · Tamil · Telugu · Kannada · Malayalam · German · French + more |
| 🧠 **Expert Mode** | 5 parallel LLM agents stream a live debate to your screen |
| 👨‍💻 **Engineer Mode** | Analysis → Plan → Unified diffs → Verification via deep model |
| 🐦 **Grok Mode** | Truth-seeking personality with real-time web + X/Twitter search |
| 💭 **Think Mode** | Visible chain-of-thought via reasoning LLM tier |
| 🔬 **Deep Research** | 5-round parallel research + full synthesis → long-form reports |
| 🖼️ **Image Generation** | Text-to-image (SD WebUI / Replicate Flux) + image editing |
| 🎬 **Video Generation** | Text-to-video via Replicate (Wan 2.1) with inline player |
| 📹 **Video Understanding** | Upload video → ffmpeg frame extract → vision model Q&A |
| 🎵 **Audio & Music** | MusicGen · Bark TTS · AudioLDM SFX via Replicate |
| 🎨 **Design Tools** | HTML mockups · Mermaid diagrams · SVG illustrations — live preview |
| 📑 **Document Creation** | Native PDF · DOCX · PPTX · XLSX from a prompt — formatted, downloadable |
| 🖥️ **Computer Use** | LLM-planned headless Playwright automation — navigate · click · extract |
| 🔀 **Multi-Modal Fusion** | Text + image + video + audio + PDF/DOCX → single synthesized response |
| 💼 **Career Engine** | GitHub analysis · job scraping · per-session tailored resume generation |
| 🏛️ **Self-Evolving Architect** | 5-agent debate proposes improvements → auto git apply + commit |
| 🩺 **Self-Healing Worker** | Monitors API health + Redis + system resources every 60s |
| 🛡️ **Security Bodyguard** | Real-time threat monitoring — SSH · network scans · nginx logs |
| 🔴 **Panic Lockdown** | Voice-triggered killswitch with Redis-backed cross-worker state |
| 🧬 **Biometric Gate** | ECAPA-TDNN voice-print locks all restricted data to owner only |
| 🎙️ **Voice Interface** | Speak to IRA — she responds with sentence-streaming Kokoro TTS |
| 🎓 **Supracloud Tutor** | Socratic teaching mode — hints only, never spoon-feeds |
| 📅 **Calendar Sync** | Cal.com v2 integration · meeting reminders · Google Calendar support |
| 📦 **Daily Backup** | Automated pg_dump + gzip at 03:00 UTC · 7-day retention · one-click restore |

</div>

---

## ⚡ Quick Start

IRA runs **native on Windows** (Shadow PC) — Ollama + the Hermes gateway, no Docker.
Bring up the whole stack with the native launcher:

```powershell
# 1 — Clone
git clone https://github.com/Praveenkumar101508/private-Jarvis.git
cd private-Jarvis\supracloud-jarvis

# 2 — Configure: copy .env.example -> .env and fill in the secrets
copy .env.example .env

# 3 — Start the full native stack (Postgres, Memurai, Ollama, Hermes gateway,
#      SearXNG/Crawl4AI, ira-api, frontend) with health checks, in order:
pwsh -File .\start-ira.ps1

# 4 — Verify per-pillar health
#      GET http://127.0.0.1:8000/health/detail
```

> The old `docker compose up` path is **retired** (there is no docker-compose.yml).
> `start-ira.ps1` prints an `OK`/`WARN`/`FAIL` line per service and a final
> `ALL UP`. SearXNG/Crawl4AI are optional — web research fails soft without them.
> Pull models first on the Shadow box: `ollama pull qwen3:14b` (+ `qwen2.5vl` for vision).

### Prerequisites

| Requirement | Details |
|:------------|:--------|
| 🐧 **OS** | Ubuntu 22.04+ · Linux · WSL2 |
| 🐳 **Docker** | Docker + Docker Compose v2 |
| 🎮 **GPU** | NVIDIA GPU with 20 GB+ VRAM (RTX A4500 or better) |
| 💾 **RAM** | 32 GB+ recommended (16 GB minimum) |
| 💿 **Disk** | 20 GB+ for model weights |
| 🔑 **Tools** | `openssl` · `git` · `nvidia-container-toolkit` |

### Deployment Modes

| Mode | Hardware | Models | Privacy |
|:-----|:---------|:-------|:--------|
| 🔒 **Full-Local** *(Recommended)* | NVIDIA GPU 20 GB+ | Qwen3-8B + Qwen3-14B | **Zero cloud calls** |
| 🔀 **Hybrid** | Any GPU / CPU | Local LLMs + selected cloud APIs | Chat local, media cloud |
| 💻 **Dev Mode** | Any machine (CPU-only) | Ollama `qwen3:8b` | Local development |

#### Dev Mode (no GPU)
```bash
ollama pull qwen3:8b
# Add to .env:
DEV_MODE=true
DEV_MODEL=qwen3:8b
OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
```

#### Cloud Mode (8×H100)
```bash
docker compose -f docker-compose.yml -f docker-compose.cloud.yml up -d
# Adds: vllm-reasoning (DeepSeek-R1 671B) + vllm-vision (Qwen3-VL-72B)
```

---

## 🏗️ Architecture

```
                    📱 Phone (Telegram alerts + PWA app)
                                │  ▲
                    Cloudflare  │  │  push notifications
                    Tunnel      │  │
                                ▼  │
                          ┌─────────────┐
                          │   nginx     │
                          │ TLS 1.3+CSP │
                          │ rate limit  │
                          └──────┬──────┘
                                 │
           ┌─────────────────────┼──────────────────────┐
           ▼                     ▼                      ▼
    ┌──────────────┐   ┌─────────────────┐   ┌─────────────────┐
    │  Frontend    │   │   IRA API       │   │   LiveKit       │
    │ Next.js 14   │   │ FastAPI 0.115   │   │ WebRTC voice    │
    │ PWA · TS     │   │ LangGraph       │   │ server          │
    │ Tailwind CSS │   │ 17 route mods   │   └─────────────────┘
    └──────────────┘   └────────┬────────┘
                                │
        ┌───────────────────────┼──────────────────────┐
        ▼                       ▼                      ▼
  ┌───────────┐         ┌──────────────┐      ┌─────────────────┐
  │ vLLM Fast │         │  vLLM Deep   │      │  IRA Worker     │
  │ Qwen3-8B  │         │ Qwen3-14B    │      │ APScheduler     │
  │ ~1–2s TTFT│         │ ~5–8s TTFT   │      │ 8 scheduled jobs│
  └───────────┘         └──────────────┘      └─────────────────┘
                          (optional)
                       ┌──────────────┐
                       │vLLM Reasoning│
                       │DeepSeek-R1 / │
                       │Qwen3-32B     │
                       └──────────────┘
           ┌───────────────────────────────────┐
           ▼                                   ▼
  ┌─────────────────────┐           ┌─────────────────────┐
  │    PostgreSQL 16     │           │      Redis 7         │
  │  + pgvector RAG      │           │  cache · lockdown   │
  │  HNSW index          │           │  state · rate limits │
  │  per-user scoped     │           │  design/doc store    │
  └─────────────────────┘           └─────────────────────┘
```

### 10 Docker Services

| Service | Role |
|:--------|:-----|
| 🐘 `postgres` | PostgreSQL 16 + pgvector — conversations · memory · tasks · security events |
| ⚡ `redis` | Redis 7 — cache · lockdown state · rate limits · design/doc artefact store |
| 🚀 `vllm-fast` | Qwen3-8B AWQ — fast tier (chat, classification) |
| 🧠 `vllm-deep` | Qwen3-14B AWQ — deep tier (code, research, analysis) |
| 🎙️ `livekit` | LiveKit WebRTC — voice call transport |
| 🤖 `ira-api` | FastAPI application — all HTTP/SSE/WebSocket endpoints |
| ⏰ `ira-worker` | Background worker — briefings · security scans · backups · self-healing |
| 🗣️ `ira-voice` | Voice pipeline — Whisper STT + Kokoro TTS + ECAPA-TDNN biometrics |
| 🖥️ `frontend` | Next.js 14 PWA frontend |
| 🔀 `nginx` | Reverse proxy — TLS 1.3 · CSP · rate limiting · WebSocket + LiveKit proxying |

### LangGraph Agent Pipeline

```
START
  → 🧠 retrieve_memory      (HNSW vector search — per-user scoped)
  → 🗂️  classify             (keyword + LLM fallback routing)
  → 🧬 biometric_gate        (voice-print / JWT owner check)
  ↓
  ┌─────────────────────────────────────────────────────┐
  │ 💬 conversational │ 🔬 researcher │ 🛡️ security    │
  │ 🎨 creator        │ ⚙️  executor   │ 💼 career      │
  │ 🌐 website        │ 🎓 tutor      │ 🖥️  digital     │
  └─────────────────────────────────────────────────────┘
  ↓
  → 💾 store_interaction     (persist + async BGE embedding)
END
```

### Self-Evolving Architect Team (5 Agents)

```
"architect propose"
         │
         ▼
  ┌─────────────────────────────────────────┐
  │           Wave 1 — Parallel             │
  ├─────────────────────┬───────────────────┤
  │ 🔍 Researcher       │ 💡 Creator        │
  │ (gap analysis vs    │ (unique ideas)    │
  │  Grok/Claude/Gemini)│                   │
  └─────────────────────┴───────────────────┘
         │                         │
         ▼                         ▼
  ┌─────────────────────────────────────────┐
  │           Wave 2 — Parallel             │
  ├─────────────────────┬───────────────────┤
  │ ⚠️  Critic           │ 🔧 Executor       │
  │ (risk)              │ (feasibility)     │
  └─────────────────────┴───────────────────┘
         │
         ▼
  👑 Supervisor — live debate stream
         │
  "architect apply" → git apply + git commit
```

### Expert Mode (5 Parallel Agents)

```
User triggers Expert Mode  ─────►  3 sessions/hour per user
         │
         ▼
  ┌──────────────────────────────────────────────────────┐
  │  🔍 Researcher    │  ⚠️  Critic    │  🔧 Executor   │
  │  (deep analysis)  │  (challenges)  │  (implement)   │
  ├───────────────────┴────────────────┴────────────────┤
  │  💡 Creator (novel approaches) │ 👑 Supervisor      │
  └────────────────────────────────────────────────────┘
         │
         ▼
  Live streaming → collapsible UI panel — all 5 perspectives visible
```

---

## 📖 Feature Usage Guide

### Chat Modes

| Mode | How to Activate | What It Does |
|:-----|:---------------|:-------------|
| 💬 **Assistant** *(default)* | Normal message | Routes to the best specialist agent |
| 🐦 **Grok Mode** | Toggle in toolbar | Truth-seeking personality + live web + X search |
| 💭 **Think Mode** | Toggle in toolbar | Shows reasoning chain using reasoning LLM |
| 👨‍💻 **Engineer Mode** | Toggle in toolbar | Analysis → Plan → Diffs → Verify |
| 🧠 **Expert Mode** | Toggle in toolbar | 5 parallel agents debate live (3/hour limit) |
| 🎓 **Tutor Mode** | Toggle in sidebar | Socratic teaching · evaluates code · hints only |
| 🔍 **DeepSearch** | Toggle in toolbar | Multi-round web search refinement |

### 🖼️ Image, Video, Audio Commands

| What You Say | What Happens |
|:-------------|:-------------|
| "generate an image of a sunset" | Text-to-image via SD WebUI or Replicate Flux |
| "edit this image: make it futuristic" + upload | InstructPix2Pix editing via Replicate |
| "generate a 5-second video of ocean waves" | Text-to-video via Replicate Wan 2.1 |
| "what is happening in this video?" + upload | Frame extraction → vision model analysis |
| "compose a relaxing lo-fi track" | MusicGen via Replicate |
| "text to speech: Hello world" | Bark TTS synthesis |
| "create a sound effect of rain" | AudioLDM SFX via Replicate |
| "transcribe this audio" + upload | Whisper via Replicate |

### 📑 Document Creation

| Command | Output |
|:--------|:-------|
| "create a PDF report about AI trends" | Formatted PDF with download button |
| "write a Word document: project proposal" | `.docx` file |
| "make a PowerPoint: 5 slides on cloud security" | `.pptx` presentation |
| "generate an Excel spreadsheet with Q1 budget" | `.xlsx` workbook |

### 🎨 Design Tools

| Command | Output |
|:--------|:-------|
| "design a landing page for a SaaS product" | HTML mockup (live browser preview) |
| "draw an ER diagram for a blog database" | Mermaid diagram (rendered in browser) |
| "create an SVG logo for SupraCloud" | SVG illustration |

### 🛡️ Security Commands *(Owner Only)*

| Voice / Chat Command | Action |
|:---------------------|:-------|
| "IRA, scan for threats" | Network scan + nginx/SSH log analysis |
| "IRA, lock down the system" | Redis-backed lockdown across all workers + Telegram alert |
| "IRA, lift lockdown" | Restores normal operations |
| "IRA, text my phone: I'm heading out" | Dispatches message to your Telegram |

### 🏛️ Self-Evolving Architect

```bash
"architect propose new features"   → 5-agent debate proposes ranked improvements
"architect implement [feature]"    → Deep LLM writes unified diffs
"architect apply"                  → Applies diffs, commits to git
```

### 💼 Career Commands

| Command | Action |
|:--------|:-------|
| "IRA, analyze my GitHub" | Scans 3 most recent repos · language stats · summaries |
| "IRA, scrape [LinkedIn/Indeed URL]" | Extracts job title · company · full requirements |
| "IRA, tailor my resume for this job" | Rewrites bullet points to match the job |
| "IRA, prep me for the interview at [URL]" | Full pipeline: scrape + analyze + tailor |

> **Setup:** Add `APIFY_API_TOKEN` (free at apify.com) and `GITHUB_TOKEN` to `.env`. Create `ira/base_resume.md` with your resume in Markdown.

---

## 🎙️ Voice Interface

IRA uses **LiveKit WebRTC** + **Faster-Whisper** (STT) + **Kokoro TTS**.

✅ What works:
- English voice conversations with full LLM context
- Voice biometric authentication (requires enrolment)
- Multilingual speech recognition (Whisper detects 99 languages)

⚠️ Known limitations:
- TTS is English only (Kokoro `af_bella` voice)
- Indic language responses are synthesised as English phonetics
- First voice session after restart takes 30–60 s while Whisper loads

### Biometric Enrolment

```bash
# 1. Get a challenge phrase (anti-replay protection)
CHALLENGE=$(curl -s -H "Authorization: Bearer $TOKEN" \
  https://your-domain/api/v1/voice/challenge | jq -r .challenge_id)

# 2. Record yourself (3–10 WAV files, 16kHz mono, ≥1s each)
#    ffmpeg -i input.m4a -ar 16000 -ac 1 -sample_fmt s16 voice1.wav

# 3. Submit for enrolment
curl -X POST https://your-domain/api/v1/voice/enroll \
  -H "Authorization: Bearer $TOKEN" \
  -F "challenge_id=${CHALLENGE}" \
  -F "audio_files=@voice1.wav" \
  -F "audio_files=@voice2.wav" \
  -F "audio_files=@voice3.wav"
```

> 💡 Record in a quiet room, speaking naturally for 3–5 seconds per clip.

---

## 🔒 Security Architecture

<div align="center">

| Layer | Protection |
|:------|:-----------|
| 🌐 **Network** | Cloudflare Tunnel — no open ports exposed to internet |
| 🔐 **TLS** | nginx TLS 1.3 only · HSTS · full CSP headers |
| 🔑 **Authentication** | JWT HS256 + bcrypt admin password (constant-time comparison) |
| 🔢 **2FA (TOTP)** | Optional TOTP — enrol via `/auth/totp/enroll` · activate via `/auth/totp/verify` |
| 🧬 **Biometrics** | ECAPA-TDNN voice gate (cosine similarity ≥ 0.75) with anti-replay challenge |
| 🛡️ **SSRF Protection** | All HTTP calls validated by `url_safety.py` (CIDR ranges + live DNS resolution) |
| 🗄️ **Database** | PostgreSQL bound to `127.0.0.1` · per-user memory isolation |
| ⚙️ **Executor** | Allowlist-only commands · path traversal blocked · `shell=False` everywhere |
| 📁 **File Uploads** | 50 MB cap enforced before body enters RAM · `is_relative_to()` path guard |
| 📨 **Telegram Alerts** | HTML parse mode + `html.escape()` on all user-controlled data |
| 🪙 **Token Storage** | `sessionStorage` only — cleared on browser close |
| 🔴 **Lockdown State** | Redis-backed — consistent across all uvicorn workers |
| 👁️ **Security Watchdog** | 60 s scan cycle — nginx logs · SSH logs · system metrics |

</div>

### Dual-Role Clearance System

```
🌍 Public Domain  ─── anyone can ask (general questions · research · chat · tutorials)
🔒 Restricted     ─── owner only (security logs · credentials · personal data · admin ops)

Text requests:   Admin JWT → is_owner = True → full access
Voice requests:  ECAPA-TDNN cosine ≥ 0.75 → is_owner = True automatically
```

---

## 💾 Backup & Restore

IRA runs an automatic database backup every day at **03:00 UTC**:

```bash
# List available backups
curl -H "Authorization: Bearer <jwt>" https://your-domain/api/v1/backup/list

# Create a manual backup now
curl -X POST -H "Authorization: Bearer <jwt>" https://your-domain/api/v1/backup/create

# Restore from a specific backup
curl -X POST -H "Authorization: Bearer <jwt>" \
  -H "Content-Type: application/json" \
  -d '{"filename": "ira_backup_20260527_030001.sql.gz"}' \
  https://your-domain/api/v1/backup/restore
```

> Stored at `/backups/` volume · `pg_dump` + gzip · retention configurable via `BACKUP_KEEP`

---

## 🌐 API Reference (Key Endpoints)

<div align="center">

| Method | Endpoint | Description |
|:------:|:---------|:------------|
| `POST` | `/auth/token` | 🔑 Get JWT token |
| `POST` | `/auth/totp/enroll` | 🔢 Enrol TOTP two-factor |
| `POST` | `/auth/totp/verify` | ✅ Activate TOTP after confirming app works |
| `POST` | `/api/v1/chat/stream` | 💬 Streaming chat (SSE) |
| `POST` | `/api/v1/chat/expert` | 🧠 Expert Mode — 5 agents (SSE) |
| `POST` | `/api/v1/chat/vision` | 👁️ Vision analysis (SSE) |
| `POST` | `/api/v1/image/generate` | 🖼️ Text-to-image (SSE) |
| `POST` | `/api/v1/image/edit` | ✏️ Image editing (SSE) |
| `POST` | `/api/v1/video/generate` | 🎬 Text-to-video (SSE) |
| `POST` | `/api/v1/video/understand` | 📹 Video analysis (SSE) |
| `POST` | `/api/v1/audio/generate` | 🎵 Music/SFX generation (SSE) |
| `POST` | `/api/v1/audio/tts` | 🗣️ Text-to-speech (SSE) |
| `POST` | `/api/v1/audio/transcribe` | 📝 Speech-to-text (SSE) |
| `POST` | `/api/v1/design/generate` | 🎨 HTML/Mermaid/SVG design (SSE) |
| `GET`  | `/api/v1/design/download/{id}` | ⬇️ Download design artefact |
| `POST` | `/api/v1/document/create` | 📄 PDF/DOCX/PPTX/XLSX (SSE) |
| `GET`  | `/api/v1/document/download/{id}` | ⬇️ Download document |
| `POST` | `/api/v1/computer/use` | 🖥️ Browser automation (SSE) |
| `POST` | `/api/v1/research/deep` | 🔬 5-round deep research (SSE) |
| `POST` | `/api/v1/multimodal/analyse` | 🔀 Multi-modal fusion (SSE) |
| `POST` | `/api/v1/architect/propose` | 🏛️ Architect proposal (SSE) |
| `POST` | `/api/v1/architect/apply` | ✅ Apply diffs + commit |
| `GET`  | `/api/v1/voice/token` | 🎙️ LiveKit access token |
| `POST` | `/api/v1/voice/enroll` | 🧬 Biometric voice enrolment |
| `POST` | `/api/v1/calendar/event` | 📅 Create Cal.com booking |
| `DELETE` | `/api/v1/calendar/event/{id}` | ❌ Cancel booking |
| `POST` | `/api/v1/files/upload` | 📁 Upload persistent file |
| `GET`  | `/api/v1/files` | 📂 List your files |
| `GET`  | `/api/v1/files/{id}` | ⬇️ Download file |
| `DELETE` | `/api/v1/files/{id}` | 🗑️ Delete file |
| `POST` | `/api/v1/backup/create` | 💾 Manual backup |
| `GET`  | `/health` | 💚 Service health check |

</div>

> All streaming endpoints use **Server-Sent Events (SSE)**. Connect with `EventSource` or `fetch()` + `ReadableStream`.

---

## 🛠️ Tech Stack

<div align="center">

| Layer | Technology |
|:------|:-----------|
| 🖥️ **API Framework** | FastAPI 0.115.5 + Python 3.11 |
| 🧠 **Agent Framework** | LangGraph 0.2.73 + LangChain 0.3.13 |
| ⚡ **LLM Inference** | vLLM (OpenAI-compatible API) |
| 🚀 **Fast Model** | Qwen3-8B AWQ — ~1–2s TTFT |
| 🔬 **Deep Model** | Qwen3-14B AWQ — ~5–8s TTFT |
| 💭 **Reasoning Model** | DeepSeek-R1 / Qwen3-32B *(optional 3rd tier)* |
| 🧮 **Embeddings** | BGE-large-en-v1.5 (1024-dim · CPU · HNSW · per-user scoped) |
| 🗄️ **Vector DB** | PostgreSQL 16 + pgvector |
| ⚡ **Cache / State** | Redis 7 |
| 🎤 **Voice STT** | Faster-Whisper large-v3 (CPU · scipy resampling) |
| 🔊 **Voice TTS** | Kokoro-82M (24kHz · sentence-streaming · multi-language) |
| 📡 **Voice Transport** | LiveKit WebRTC |
| 🧬 **Biometrics** | SpeechBrain ECAPA-TDNN (CPU · cosine similarity ≥ 0.75) |
| 🌐 **Browser Automation** | Playwright 1.47 headless Chromium (SSRF + DNS-rebinding protected) |
| 🖼️ **Image Generation** | Stable Diffusion WebUI (local) / Replicate Flux Schnell (cloud) |
| 🎬 **Video Generation** | Replicate Wan 2.1 |
| 🎵 **Audio Generation** | Replicate MusicGen + Bark TTS + AudioLDM SFX |
| 🔍 **Web Search** | DuckDuckGo (multi-round DeepSearch) |
| 🐦 **X/Twitter Search** | X API v2 → twitterapi.io → DDG (country-aware) |
| 💼 **Job Scraping** | Apify (LinkedIn + Indeed) |
| 📁 **Document Gen** | reportlab (PDF) + python-docx + python-pptx + openpyxl |
| 🖥️ **Frontend** | Next.js 14 + TypeScript + Tailwind CSS |
| 📱 **Mobile Access** | Progressive Web App + Cloudflare Tunnel |
| 🔀 **Reverse Proxy** | nginx 1.27 (TLS 1.3 · HSTS · CSP · 100 MB upload limit) |
| 🐳 **Container** | Docker Compose (10 services) |
| 🎮 **GPU Target** | NVIDIA RTX A4500 20 GB VRAM (or any CUDA-capable GPU) |
| ☁️ **Cloud Upgrade** | 8×H100 80 GB (Qwen3-72B + DeepSeek-R1 671B) via cloud overlay |

</div>

---

## ☁️ Cloud API Dependencies

**Fully local (zero external keys needed):** chat · memory · voice · biometrics · research · security monitoring · briefings · architect team · engineer mode · expert mode · tutor · document creation · design tools · computer use · multi-modal analysis · self-healing · daily backup.

External API keys unlock *additional* capabilities:

| Feature | Service | Env Var | Free Tier? |
|:--------|:--------|:--------|:----------:|
| Image generation | Replicate (Flux Schnell) | `REPLICATE_API_TOKEN` | ✅ |
| Video generation | Replicate (Wan 2.1) | `REPLICATE_API_TOKEN` | ❌ |
| Music generation | Replicate (MusicGen) | `REPLICATE_API_TOKEN` | ✅ |
| X/Twitter search | X API v2 | `TWITTER_BEARER_TOKEN` | ✅ |
| LinkedIn scraping | Apify | `APIFY_API_TOKEN` | ✅ |
| GitHub analysis | GitHub API | `GITHUB_TOKEN` | ✅ |
| Telegram alerts | Telegram Bot API | `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | ✅ |
| Email alerts | SMTP | `SMTP_HOST/USER/PASS/TO` | varies |
| Calendar sync | Cal.com API v2 | `CALCOM_API_KEY` | ✅ |

---

## ⚙️ Environment Variables

```env
# ── Identity ────────────────────────────────────────────────
OWNER_NAME=Praveenkumar
IRA_ADMIN_USERNAME=admin
IRA_ADMIN_PASSWORD=your_secure_password

# ── LLM Endpoints ───────────────────────────────────────────
VLLM_FAST_URL=http://vllm-fast:8001/v1
VLLM_DEEP_URL=http://vllm-deep:8002/v1
VLLM_FAST_MODEL=qwen3-fast
VLLM_DEEP_MODEL=qwen3-deep
VLLM_REASONING_URL=              # optional — enables Think Mode tier

# ── Dev Mode (CPU, no GPU) ──────────────────────────────────
DEV_MODE=false
OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
DEV_MODEL=qwen3:8b

# ── Notifications ────────────────────────────────────────────
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# ── External APIs (all optional) ────────────────────────────
REPLICATE_API_TOKEN=
TWITTER_BEARER_TOKEN=
APIFY_API_TOKEN=
GITHUB_TOKEN=
CALCOM_API_KEY=

# ── Voice ────────────────────────────────────────────────────
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=
IRA_VOICE=af_bella               # or af_heart

# ── Backup ───────────────────────────────────────────────────
BACKUP_DIR=/backups
BACKUP_KEEP=7                    # days of retention

# ── Timezone ─────────────────────────────────────────────────
BRIEFING_TIMEZONE=Asia/Kolkata
```

> Full template with all variables: `.env.example`

---

## 📁 Project Structure

```
private-Jarvis/
└── supracloud-jarvis/
    ├── 🐳 docker-compose.yml           ← 10 services
    ├── 🐳 docker-compose.cloud.yml     ← 8×H100 cloud overlay
    ├── 🔀 nginx/nginx.conf             ← TLS 1.3, CSP, LiveKit proxy
    ├── 🎙️  livekit/livekit.yaml         ← LiveKit server config
    ├── 🗄️  postgres/
    │   ├── init.sql                    ← Base schema
    │   ├── 002_phase4.sql              ← Tasks, calendar, monitor state
    │   ├── 003_biometrics.sql          ← Voice profiles + audit table
    │   ├── 004_memory_isolation_hnsw.sql
    │   ├── 005_files.sql               ← Persistent file storage
    │   ├── 006_totp.sql                ← TOTP 2FA secrets
    │   └── 007_totp_enabled.sql        ← TOTP enabled gate migration
    ├── 📜 scripts/
    │   ├── setup.sh                    ← One-command server setup
    │   └── verify.sh                   ← Health check all services
    ├── 🖥️  frontend/
    │   ├── public/manifest.json        ← PWA manifest (voice shortcut)
    │   └── components/
    │       ├── ChatInterface.tsx        ← SSE streaming, all mode toggles
    │       ├── VoiceOrb.tsx            ← LiveKit voice, pulse animation
    │       └── Sidebar.tsx             ← Mode selector, conversation history
    └── 🤖 ira/
        ├── main.py                     ← FastAPI app, 19 routers registered
        ├── config.py                   ← All env vars via Pydantic Settings
        ├── agents/
        │   ├── graph.py                ← LangGraph pipeline (10 nodes)
        │   ├── supervisor.py           ← Query classifier
        │   ├── conversational.py       ← Grok-personality chat
        │   ├── researcher.py           ← Deep research agent
        │   ├── security.py             ← Threat tools (owner-only)
        │   ├── expert_mode.py          ← 5-parallel-agent Expert Mode
        │   ├── architect_agent.py      ← 5-agent evolution team
        │   └── engineer_agent.py       ← 4-step engineering mode
        ├── api/routes/
        │   ├── chat.py                 ← /chat/stream, /chat/expert
        │   ├── files.py                ← /files upload/list/download/delete
        │   ├── totp.py                 ← /auth/totp/enroll + /verify
        │   ├── calendar.py             ← /calendar/event create + cancel
        │   ├── image_gen.py            ← /image/generate, /image/edit
        │   ├── video_gen.py            ← /video/generate, /video/understand
        │   ├── audio_gen.py            ← /audio/generate, /audio/tts
        │   ├── design_tools.py         ← /design/generate, /design/download
        │   ├── document_create.py      ← /document/create, /document/download
        │   ├── deep_research.py        ← /research/deep, /research/article
        │   ├── architect.py            ← /architect/propose, /apply
        │   ├── voice.py                ← /voice/token, /voice/enroll
        │   ├── backup.py               ← /backup/list, /backup/restore
        │   ├── tasks.py                ← /tasks CRUD
        │   ├── webhooks.py             ← /webhooks/lead, /webhooks/booking
        │   └── health.py               ← /health
        ├── memory/
        │   ├── store.py                ← HNSW vector search, per-user isolation
        │   └── embeddings.py           ← BGE-large-en-v1.5 (thread-safe)
        ├── voice/
        │   ├── agent.py                ← LiveKit agent + biometric check
        │   ├── biometrics.py           ← ECAPA-TDNN speaker verification
        │   ├── stt.py                  ← Faster-Whisper (scipy resampling)
        │   └── tts.py                  ← Kokoro sentence-streaming
        ├── utils/
        │   ├── llm.py                  ← 3-tier vLLM routing + retry
        │   ├── url_safety.py           ← SSRF + DNS-rebinding protection
        │   ├── cmd_safety.py           ← Two-gate path validator
        │   ├── migrations.py           ← Idempotent schema migration runner
        │   ├── security_tools.py       ← scan_threats(), initiate_lockdown()
        │   └── db.py                   ← asyncpg connection pool
        └── worker/
            ├── scheduler.py            ← 8 cron jobs
            ├── security_monitor.py     ← nginx + SSH + CPU watchdog (60s)
            ├── self_healing.py         ← Health checks + auto remediation
            └── backup.py               ← pg_dump + 7-day retention
```

---

## 📱 Install IRA on Your Phone (PWA)

```bash
# 1 — Set up Cloudflare Tunnel (zero open ports)
curl -L --output cloudflared.deb \
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared.deb
cloudflared tunnel login
cloudflared tunnel create ira-private
cloudflared tunnel route dns ira-private ira.yourdomain.com
sudo cloudflared service install && sudo systemctl enable --now cloudflared
```

Then on your phone:
- **iPhone Safari** → Share → Add to Home Screen
- **Android Chrome** → Menu → Add to Home Screen

IRA launches full-screen — no browser chrome, dark theme, instant load. The PWA includes a **Voice Mode shortcut** to start a voice session instantly from your home screen.

---

## 🔑 Secrets Management

IRA uses [sops](https://github.com/getsops/sops) + [age](https://github.com/FiloSottile/age) for encrypted secrets.

```bash
# First-time setup
bash scripts/init-secrets.sh   # generates your age key
cp .env.example .env            # fill in your values
make secrets-encrypt            # creates .env.enc (safe to commit)

# On a new machine
mkdir -p ~/.config/sops/age && cp your-backup/keys.txt ~/.config/sops/age/
export SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt
make secrets-decrypt            # creates .env from .env.enc

# Editing secrets
make secrets-edit               # opens .env.enc, re-encrypts on save
```

---

<div align="center">

## 👤 Author

<br/>

**Praveenkumar**

[![GitHub](https://img.shields.io/badge/GitHub-Praveenkumar101508-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/Praveenkumar101508)
[![Company](https://img.shields.io/badge/Company-SupraCloud-6366f1?style=for-the-badge&logoColor=white)](https://github.com/Praveenkumar101508)

<br/>

---

*SupraCloud IRA — Private. Sovereign. Yours.*

**Built and owned by Praveenkumar · © 2026 SupraCloud**

</div>
