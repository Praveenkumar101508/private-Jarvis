# SupraCloud IRA — Private Sovereign AI Assistant

> **IRA** — Intelligent Responsive Assistant · v1.0.0  
> Built and owned by **Praveenkumar** · SupraCloud

A fully self-hosted, private AI assistant platform. IRA runs entirely on your own hardware — no data leaving your server. IRA covers the full spectrum from casual conversation to autonomous code evolution, real-time security monitoring, voice biometrics, creative media generation, deep research, and self-healing infrastructure — all in one sovereign system.

---

## Feature Status

| Feature | Status | Notes |
|---|---|---|
| Chat with memory + RAG | ✅ Production | Streaming, Think Mode, Expert Mode |
| Document creation (PDF/Word/Excel/PPT) | ✅ Production | From chat prompt |
| Document upload + analysis | ✅ Production | PDF/DOCX/TXT |
| Engineer Mode (code diffs) | ✅ Production | 4-step workflow |
| Web search + DeepSearch | ✅ Production | DuckDuckGo + X/Twitter |
| Image generation | ✅ Production | Requires Replicate API token or SD WebUI |
| Vision / image analysis | ✅ Production | Requires vLLM vision endpoint |
| Security monitoring | ✅ Production | nginx log analysis, SSH brute-force |
| Daily backups | ✅ Production | pg_dump, 7-day retention |
| Morning/evening briefings | ✅ Production | Telegram or email |
| Task + reminder management | ✅ Production | APScheduler delivery |
| Architect Evolution mode | ✅ Production | Proposal only — apply is manual |
| Career tools (resume, job scrape) | ✅ Production | Requires Apify API token |
| Voice interface | ⚠️ Beta | Works in English; see Voice section below |
| Biometric voice auth | ⚠️ Beta | Requires enrolment; see Voice section |
| Video generation | 🔧 Requires Replicate | External API |
| Audio/music generation | 🔧 Requires Replicate | External API |
| Multilingual voice | 🔧 Experimental | Indic languages use English TTS (known limitation) |
| Computer use (Playwright) | 🔧 Experimental | SSRF protections required for production |

---

## What IRA Can Do

| Capability | Description |
|---|---|
| **Multi-language Chat** | English, Hindi, Tamil, Telugu, Kannada, Malayalam, German, French + more |
| **Expert Mode** | 5 parallel LLM agents (Researcher, Critic, Executor, Creator, Supervisor) stream a live debate to your screen |
| **Engineer Mode** | Claude-style 4-step workflow: Analysis → Plan → Unified diffs → Verification using the deep model |
| **Grok Mode** | Truth-seeking personality with real-time web search + live X/Twitter search |
| **Think Mode** | Visible chain-of-thought reasoning using the reasoning tier (DeepSeek-R1 / Qwen3-32B) |
| **Deep Research** | 5-round parallel sub-question research + full synthesis — generates long-form reports and articles |
| **Image Generation** | Text-to-image (Stable Diffusion WebUI / Replicate Flux Schnell) + image editing (InstructPix2Pix) |
| **Video Generation** | Text-to-video via Replicate (Wan 2.1) with inline video player |
| **Video Understanding** | Upload a video → ffmpeg frame extraction → vision model analysis + Q&A |
| **Audio & Music** | MusicGen music composition, Bark TTS speech synthesis, audio effects (SFX) via Replicate |
| **Design Tools** | HTML mockups, Mermaid diagrams (flowchart, ER, sequence, Gantt), SVG illustrations — live preview in browser |
| **Document Creation** | Native PDF, DOCX, PPTX, XLSX generation from a prompt — formatted, downloadable |
| **Computer Use** | LLM-planned headless Playwright browser automation: navigate, click, fill, extract, screenshot |
| **Multi-Modal Fusion** | Unified pipeline: text + image + video + audio + PDF/DOCX → single synthesized response |
| **Career Engine** | GitHub analysis, LinkedIn/Indeed job scraping, per-session tailored resume generation |
| **Self-Evolving Architect** | 5-agent debate team proposes improvements; auto-implements via `git apply` + `git commit` |
| **Self-Healing Worker** | Monitors API health, Redis, system resources every 60s; performs automated remediation |
| **Security Bodyguard** | Real-time threat monitoring — SSH brute-force, network scans, CPU spikes, nginx log analysis |
| **Panic Lockdown** | Voice-triggered killswitch with Redis-backed cross-worker state + instant Telegram confirmation |
| **Biometric Gate** | ECAPA-TDNN voice-print authentication locks all restricted data to the owner only |
| **Voice Interface** | Full voice pipeline: speak to IRA, she responds with sentence-streaming Kokoro TTS |
| **Supracloud Tutor** | Socratic teaching mode — evaluates student code privately, gives hints only, never spoon-feeds answers |
| **Digital Brain** | OS control (open apps), allowlisted shell commands, headless browser + page Q&A |
| **X / Twitter Search** | Country-aware smart routing to X API v2 / twitterapi.io fallback / DuckDuckGo |
| **Web Search** | Real-time DuckDuckGo search with DeepSearch multi-round refinement |
| **Calendar Sync** | Cal.com v2 integration, meeting reminders, Google Calendar support |
| **Daily Backup** | Automated pg_dump + gzip at 03:00 UTC, 7-day retention, one-click restore |
| **Proactive Alerts** | Morning briefings, security digests, reminders via Telegram + email |
| **Business Monitor** | Lead tracking, hot-lead qualification, booking monitoring, business reports |
| **Mobile PWA** | Installable on iPhone/Android via Cloudflare Tunnel — full-screen, instant load |

---

## Architecture

```
                    Phone (Telegram alerts + PWA app)
                                │  ▲
                    Cloudflare  │  │  push notifications
                    Tunnel      │  │
                                ▼  │
                          [ nginx ]
                    TLS 1.3 + CSP + rate limiting
                                │
           ┌────────────────────┼────────────────────┐
           ▼                    ▼                     ▼
    [ Frontend ]          [ IRA API ]           [ LiveKit ]
    Next.js 14            FastAPI 0.115         WebRTC voice
    PWA · TypeScript      LangGraph 0.2.73      server
    Tailwind CSS          17 route modules
                                │
        ┌───────────────────────┼────────────────────┐
        ▼                       ▼                     ▼
  [ vLLM Fast ]         [ vLLM Deep ]         [ IRA Worker ]
  Qwen3-8B AWQ          Qwen3-14B AWQ         APScheduler
  ~1–2s TTFT            ~5–8s TTFT            8 scheduled jobs
                                              + Watchdog 60s
        │                 (optional)
        │            [ vLLM Reasoning ]
        │            DeepSeek-R1 / Qwen3-32B
        │            Think Mode + DeepSearch
        │
 ┌──────┴──────┐
 ▼             ▼
[ PostgreSQL ] [ Redis ]
+ pgvector RAG   cache + lockdown
HNSW index       state + rate limits
per-user scoped  + design/doc store
```

### 10 Docker Services

| Service | Role |
|---|---|
| `postgres` | PostgreSQL 16 + pgvector — conversations, memory, tasks, security events |
| `redis` | Redis 7 — cache, lockdown state, rate limits, design/doc artefact store |
| `vllm-fast` | Qwen3-8B AWQ — fast tier (chat, classification) |
| `vllm-deep` | Qwen3-14B AWQ — deep tier (code, research, analysis) |
| `livekit` | LiveKit WebRTC — voice call transport |
| `ira-api` | FastAPI application — all HTTP/SSE/WebSocket endpoints |
| `ira-worker` | Background worker — briefings, security scans, backups, self-healing |
| `ira-voice` | Voice pipeline — Whisper STT + Kokoro TTS + ECAPA-TDNN biometrics |
| `frontend` | Next.js 14 PWA frontend |
| `nginx` | Reverse proxy — TLS 1.3, CSP, rate limiting, WebSocket + LiveKit proxying |

### LangGraph Agent Pipeline

```
START
  → retrieve_memory        (HNSW vector search — per-user scoped)
  → classify               (keyword + LLM fallback routing)
  → biometric_gate         (voice-print / JWT owner check)
  ↓
  ┌──────────────────────────────────────────────────┐
  │ conversational │ researcher │ security │ website  │
  │ creator        │ executor   │ career   │ tutor    │
  │ digital        │            │          │          │
  └──────────────────────────────────────────────────┘
  ↓
  store_interaction         (persist + async BGE embedding)
END
```

### Self-Evolving Architect Team (5 Agents)

```
"architect propose"  →  Architect pipeline
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
         Wave 1 (parallel):                Wave 2 (parallel):
      Researcher            Creator      Critic    Executor
   (gap analysis vs      (unique ideas)  (risk)  (feasibility)
    Grok/Claude/Gemini)
              └───────────────┼───────────────┘
                              ▼
                         Supervisor
                     live debate stream
                              │
              "architect apply"  →  git apply + git commit
```

### Expert Mode (5 Parallel Agents)

```
User triggers Expert Mode (3 sessions/hour per user)
  ↓
5 agents run in parallel:
  Researcher (deep analysis) │ Critic (challenges) │ Executor (implementation)
  Creator (novel approaches) │ Supervisor (synthesis)
  ↓
Live streaming to collapsible UI panel — all 5 perspectives visible
```

### Security Watchdog (every 60 seconds)

```
run_security_scan()
  ├─ parse nginx access.log  → SQLi / XSS / path traversal / scanner UA
  ├─ parse /var/log/auth.log → SSH brute-force (≥3 from same IP → Telegram alert)
  │   └─ fallback: journalctl -u sshd  (if auth.log absent on systemd systems)
  ├─ psutil (thread-pool)    → CPU >90% → cryptominer warning push
  ├─ write security_events table
  └─ critical/high → notify() → Telegram HTML + WebSocket + Email
```

### Career Automation Pipeline

```
"IRA, tailor my resume for this job [URL]"
  ↓
Career Agent
  ├─ analyze_my_codebase()      → GitHub API: top languages, project summaries
  ├─ scrape_job_posting(url)    → Apify: title, company, requirements
  └─ generate_tailored_resume() → Deep LLM → tailored_resumes/<session_id>.md
  ↓
IRA responds: match analysis + 3 interview talking points
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| **API Framework** | FastAPI 0.115.5 + Python 3.11 |
| **Agent Framework** | LangGraph 0.2.73 + LangChain 0.3.13 |
| **LLM Inference** | vLLM (OpenAI-compatible API) |
| **Fast Model** | Qwen3-8B AWQ — ~1–2s TTFT |
| **Deep Model** | Qwen3-14B AWQ — ~5–8s TTFT |
| **Reasoning Model** | DeepSeek-R1 / Qwen3-32B (optional 3rd tier) |
| **Embeddings** | BGE-large-en-v1.5 (1024-dim, CPU, HNSW index, per-user scoped) |
| **Vector DB** | PostgreSQL 16 + pgvector |
| **Cache / State** | Redis 7 |
| **Voice STT** | Faster-Whisper large-v3 (CPU, scipy anti-aliased resampling) |
| **Voice TTS** | Kokoro-82M (24kHz, sentence-streaming, multi-language) |
| **Voice Transport** | LiveKit WebRTC |
| **Biometrics** | SpeechBrain ECAPA-TDNN (CPU, cosine similarity ≥ 0.75) |
| **Browser Automation** | Playwright 1.47 headless Chromium (SSRF + DNS-rebinding protected) |
| **Image Generation** | Stable Diffusion WebUI (local) / Replicate Flux Schnell (cloud) |
| **Video Generation** | Replicate Wan 2.1 |
| **Audio Generation** | Replicate MusicGen + Bark TTS + AudioLDM SFX |
| **Web Search** | DuckDuckGo (multi-round DeepSearch) |
| **X/Twitter Search** | X API v2 → twitterapi.io fallback → DDG (country-aware) |
| **Job Scraping** | Apify (LinkedIn + Indeed, actor IDs configurable) |
| **GitHub Analysis** | PyGithub |
| **Document Gen** | reportlab (PDF) + python-docx (DOCX) + python-pptx (PPTX) + openpyxl (XLSX) |
| **Frontend** | Next.js 14 + TypeScript + Tailwind CSS |
| **Mobile Access** | Progressive Web App + Cloudflare Tunnel |
| **Reverse Proxy** | nginx 1.27 (TLS 1.3, HSTS, CSP, 100MB upload limit) |
| **Container** | Docker Compose (10 services) |
| **GPU Target** | NVIDIA RTX A4500 20GB VRAM (or any CUDA-capable GPU) |
| **Cloud Upgrade** | 8×H100 80GB (Qwen3-72B + DeepSeek-R1 671B) via `docker-compose.cloud.yml` |

---

## Deployment Modes

| Mode | Hardware | Models | Use Case |
|---|---|---|---|
| **Full-Local (Recommended)** | NVIDIA GPU 20GB+ | Qwen3-8B + Qwen3-14B | Maximum privacy — zero cloud calls |
| **Hybrid** | Any GPU / CPU | Local LLMs + selected cloud APIs | Local chat + Replicate for images/audio |
| **Dev Mode** | Any machine (CPU-only) | Ollama (qwen3:8b) | Local development, no GPU required |

### Full-Local Mode (Default)
Set `DEV_MODE=false`. vLLM serves three model tiers:

- **Fast** — `qwen3-fast` (8B AWQ) — conversational, classification, ~1–2s
- **Deep** — `qwen3-deep` (14B AWQ) — code, research, analysis, ~5–8s
- **Reasoning** (optional) — `qwen3-reasoning` (32B+) — Think Mode, DeepSearch

### Dev Mode (CPU / No GPU)
```bash
ollama pull qwen3:8b
# Set in .env:
DEV_MODE=true
DEV_MODEL=qwen3:8b
OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
```

### Cloud Upgrade (8×H100)
```bash
docker compose -f docker-compose.yml -f docker-compose.cloud.yml up -d
# Adds: vllm-reasoning (DeepSeek-R1 671B) + vllm-vision (Qwen3-VL-72B)
```

### Known Limitations
- **Indic language voice** — Whisper large-v3 accuracy varies; Indic speaker enrolment not extensively tested
- **Biometric gate** — requires `speechbrain` + `torch+cpu` in `ira-voice` container; gate passes all traffic if not installed
- **Recurring reminders** — require `croniter>=3.0` (included in `requirements.txt`)
- **Voice STT resampling** — requires `scipy>=1.14` (included); falls back to basic decimation without it
- **Reasoning tier** — optional; if `VLLM_REASONING_URL` is empty, Think Mode falls back to the deep model

---

## Privacy & Cloud Dependencies

IRA is designed to be self-hosted, but several features optionally call external APIs:

| Feature | External Service | Data Sent |
|---|---|---|
| Image generation | Replicate (api.replicate.com) | Your image prompt |
| Image editing | Replicate | Your image + edit instruction |
| Video generation | Replicate | Your video prompt |
| Music generation | Replicate | Your music prompt |
| Job scraping | Apify (apify.com) | LinkedIn/Indeed search query |
| Voice notifications | Telegram Bot API | Notification title + body |
| X/Twitter search | Twitter API v2 or twitterapi.io | Your search query |

To run with zero external dependencies: set `IMAGE_GEN_URL` to a local Stable Diffusion WebUI, leave Replicate unconfigured, and use local Whisper for STT (already included).

---

## Cloud-Dependent Features

IRA runs fully without any of these. External API keys unlock additional capabilities:

| Feature | Service | Env var in `.env` | Free tier? |
|---|---|---|---|
| Image generation | Replicate (Flux Schnell) | `REPLICATE_API_TOKEN` | Yes (limited) |
| Image editing | Replicate (InstructPix2Pix) | `REPLICATE_API_TOKEN` | Yes |
| Video generation | Replicate (Wan 2.1) | `REPLICATE_API_TOKEN` | No |
| Music generation | Replicate (MusicGen) | `REPLICATE_API_TOKEN` | Yes |
| Audio SFX | Replicate (AudioLDM) | `REPLICATE_API_TOKEN` | Yes |
| Bark TTS (cloud) | Replicate | `REPLICATE_API_TOKEN` | Yes |
| Cloud Whisper STT | Replicate | `REPLICATE_API_TOKEN` | Yes |
| X/Twitter search | X API v2 | `TWITTER_BEARER_TOKEN` | Yes (Basic) |
| X search fallback | twitterapi.io | `X_FALLBACK_API_KEY` | ~$5/month |
| LinkedIn job scraping | Apify | `APIFY_API_TOKEN` | Yes (limited) |
| Indeed job scraping | Apify | `APIFY_API_TOKEN` | Yes (limited) |
| GitHub repo analysis | GitHub API | `GITHUB_TOKEN` | Yes |
| Telegram alerts | Telegram Bot API | `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | Free |
| Email notifications | SMTP | `SMTP_HOST/USER/PASS/TO` | Varies |
| Calendar sync | Cal.com API v2 | `CALCOM_API_KEY` | Yes |
| Google Calendar | GCP service account | `GOOGLE_SERVICE_ACCOUNT_JSON` | Yes |

**Fully local (no external keys needed):** chat, memory, voice, biometrics, research, security monitoring, briefings, architect team, engineer mode, expert mode, tutor, document creation (PDF/DOCX/PPTX/XLSX), design tools, computer use, multi-modal analysis, self-healing, daily backup.

---

## Quick Start

### Prerequisites
- Ubuntu 22.04+ (or Linux / WSL2)
- Docker + Docker Compose v2
- NVIDIA GPU + drivers + `nvidia-container-toolkit`
- 32GB+ RAM recommended (16GB minimum for fast+deep models)
- 20GB+ available disk space (model weights)
- For local LLM: GPU with 20GB+ VRAM (RTX A4500 or better)
- For dev mode without GPU: Ollama installed with `qwen3:8b` pulled
- `openssl` (for secret generation)
- `git` (for architect apply pipeline)

### Step 1 — Clone
```bash
git clone -b claude/setup-private-session-1gF9a \
  https://github.com/Praveenkumar101508/private-Jarvis.git
cd private-Jarvis/supracloud-jarvis
```

### Step 2 — Setup
```bash
bash scripts/setup.sh
```
Creates `.env`, auto-generates secrets, creates TLS cert, prompts for admin password.

### Step 3 — Build and start
```bash
docker compose build
docker compose up -d
```
First start pulls ~15GB of model weights. Check `docker compose logs -f ira-api` until you see `Application startup complete`.

### Step 4 — Verify
```bash
bash scripts/verify.sh
```
Checks all 10 containers are healthy, models are loaded, API is responding.

### Step 5 — Open IRA
Visit `https://your-server-ip`. Default login: `admin` / (password set during setup).

---

## Feature Usage Guide

### Chat Modes

| Mode | How to activate | What it does |
|---|---|---|
| **Assistant** (default) | Normal message | Routes to the best specialist agent |
| **Grok Mode** | Toggle in toolbar | Truth-seeking personality + live web + X search |
| **Think Mode** | Toggle in toolbar | Shows reasoning chain; uses reasoning LLM tier |
| **Engineer Mode** | Toggle in toolbar | 4-step engineering workflow (Analysis → Plan → Diffs → Verify) |
| **Expert Mode** | Toggle in toolbar | 5 parallel agents debate your question live (3/hour limit) |
| **Tutor Mode** | Toggle in sidebar | Socratic teaching; evaluates code privately, gives hints only |
| **DeepSearch** | Toggle in toolbar | Multi-round web search refinement |

### Image, Video, Audio

| Command | Action |
|---|---|
| "generate an image of a sunset" | Text-to-image via SD WebUI or Replicate Flux |
| "edit this image: make it futuristic" + upload | InstructPix2Pix editing via Replicate |
| "generate a 5-second video of ocean waves" | Text-to-video via Replicate Wan 2.1 |
| "what is happening in this video?" + upload | Frame extraction → vision model analysis |
| "compose a relaxing lo-fi track" | MusicGen via Replicate |
| "text to speech: Hello world" | Bark TTS synthesis |
| "create a sound effect of rain" | AudioLDM SFX via Replicate |
| "transcribe this audio" + upload | Whisper via Replicate |

### Design Tools

| Command | Output |
|---|---|
| "design a landing page for a SaaS product" | HTML mockup (live browser preview) |
| "draw an ER diagram for a blog database" | Mermaid diagram (rendered in browser) |
| "create an SVG logo for SupraCloud" | SVG illustration |

### Document Creation

| Command | Output |
|---|---|
| "create a PDF report about AI trends" | Formatted PDF (download button) |
| "write a Word document: project proposal" | .docx file |
| "make a PowerPoint: 5 slides on cloud security" | .pptx presentation |
| "generate an Excel spreadsheet with Q1 budget" | .xlsx workbook |

### Computer Use

| Command | Action |
|---|---|
| "browse https://example.com and summarize the homepage" | Playwright headless visit + LLM summary |
| "take a screenshot of https://example.com" | Returns base64 PNG |
| "go to the pricing page on that site and extract the plans" | Multi-step browser automation |

### Research & Writing

| Command | Action |
|---|---|
| "deep research: quantum computing in 2026" | 5-round parallel research + synthesis |
| "write a 2000-word article about neural networks" | Long-form article with style control |
| "write a formal research report on cybersecurity trends" | Structured report with citations |

### Self-Evolving Architect

```
"architect propose new features"   → 5-agent debate proposes ranked improvements
"architect implement [feature]"    → Deep LLM writes unified diffs
"architect apply"                  → Applies diffs, commits to git (exact phrase required)
```

### Security Commands (Owner Only)

| Voice / Chat Command | Action |
|---|---|
| "IRA, scan for threats" | Network scan + nginx/SSH log analysis |
| "IRA, lock down the system" | Redis-backed lockdown across all workers + Telegram alert |
| "IRA, lift lockdown" | Restores normal operations |
| "IRA, text my phone: I'm heading out" | Dispatches message to your Telegram |

### Career Commands

| Command | Action |
|---|---|
| "IRA, analyze my GitHub" | Scans 3 most recent repos, language stats, summaries |
| "IRA, scrape [LinkedIn/Indeed URL]" | Extracts job title, company, full requirements |
| "IRA, tailor my resume for this job" | Rewrites bullet points to match the job |
| "IRA, prep me for the interview at [URL]" | Full pipeline: scrape + analyze + tailor |

> **Setup:** Add `APIFY_API_TOKEN` (free at apify.com) and `GITHUB_TOKEN` to `.env`.  
> Create `ira/base_resume.md` with your resume in Markdown format.

---

## Voice Interface

IRA uses LiveKit WebRTC + Faster-Whisper (STT) + Kokoro TTS.

**What works:**
- English voice conversations with full LLM context
- Voice biometric authentication (requires enrolment — see below)
- Multilingual speech recognition (Whisper detects 99 languages)

**Known limitations:**
- Text-to-speech is English only (Kokoro af_bella voice)
- Hindi, Tamil, Telugu and other Indic language responses are synthesised as English phonetics — this sounds broken. Full Indic TTS is planned for a future release.
- First voice session after restart may take 30–60 seconds while Whisper loads

**Biometric enrolment (required before voice auth works):**
```bash
# 1. Get a challenge phrase
curl -H "Authorization: Bearer $TOKEN" https://your-domain/api/v1/voice/challenge

# 2. Record yourself saying the phrase (3–10 WAV files, 16kHz mono)

# 3. Submit for enrolment
curl -X POST https://your-domain/api/v1/voice/enroll \
  -H "Authorization: Bearer $TOKEN" \
  -F "challenge_id=<from step 1>" \
  -F "audio_files=@recording1.wav" \
  -F "audio_files=@recording2.wav" \
  -F "audio_files=@recording3.wav"
```

Until enrolled, all voice sessions run as public-access (restricted commands blocked).

> Convert to correct format: `ffmpeg -i input.m4a -ar 16000 -ac 1 -sample_fmt s16 recording1.wav`

---

## Biometric Security Gate

IRA implements a **Dual-Role Clearance System**:

- **Public domain** — anyone can ask (general questions, research, chat, tutorials)
- **Restricted domain** — owner only (security logs, credentials, personal data, admin operations)

### Text requests
Admin JWT → `is_owner = True` → full access to all restricted operations.

### Voice requests
ECAPA-TDNN voice embedding → cosine similarity ≥ 0.75 → `is_owner = True` automatically.

### Enrol your voice
```bash
# First get a challenge token (anti-replay protection)
CHALLENGE=$(curl -s -H "Authorization: Bearer <jwt>" \
  https://your-domain/api/v1/voice/challenge | jq -r .challenge_id)

# Enrol with 3 clean voice samples (WAV, 16kHz mono 16-bit PCM, ≥1s each)
curl -X POST https://your-domain/api/v1/voice/enroll \
  -H "Authorization: Bearer <jwt>" \
  -F "challenge_id=${CHALLENGE}" \
  -F "audio_files=@voice1.wav" \
  -F "audio_files=@voice2.wav" \
  -F "audio_files=@voice3.wav"
```
> Tip: Record in a quiet room, speaking naturally for 3–5 seconds per clip.  
> Convert to correct format: `ffmpeg -i input.m4a -ar 16000 -ac 1 -sample_fmt s16 voice1.wav`

---

## Backup & Restore

IRA runs an automatic database backup every day at 03:00 UTC:

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

Backups: `pg_dump` + gzip, stored in `/backups/` volume, 7-day retention (configurable via `BACKUP_KEEP`).

---

## Security Architecture

| Layer | Protection |
|---|---|
| **Network** | Cloudflare Tunnel — no open ports exposed to internet |
| **TLS** | nginx TLS 1.3 only, HSTS, full CSP headers |
| **Authentication** | JWT HS256 + bcrypt admin password (constant-time comparison) |
| **Biometrics** | ECAPA-TDNN voice gate (cosine similarity ≥ 0.75) with anti-replay challenge |
| **SSRF Protection** | All browser/HTTP calls validated by `url_safety.py` (CIDR ranges + live DNS resolution) |
| **Database** | PostgreSQL bound to `127.0.0.1`, per-user memory isolation |
| **Executor** | Allowlist-only commands, path traversal blocked, `shell=False` everywhere |
| **File Uploads** | 64KiB chunk streaming — size cap enforced before body enters RAM |
| **Telegram Alerts** | HTML parse mode + `html.escape()` on all user-controlled data |
| **Token Storage** | `sessionStorage` only — cleared on browser close, no `localStorage` |
| **Lockdown State** | Redis-backed — consistent across all uvicorn workers |
| **Security Watchdog** | 60s scan cycle — nginx logs, SSH logs (file + journalctl fallback), system metrics |
| **Design Downloads** | `Content-Disposition: attachment` — LLM-generated HTML/SVG never rendered inline |

---

## Webhook Integration

Point your website contact form or booking system to:

```bash
# New lead
POST https://your-domain/webhooks/lead
Headers: X-Webhook-Secret: <WEBHOOK_SECRET from .env>
Body: {"name": "...", "email": "...", "message": "...", "source": "website"}

# New booking
POST https://your-domain/webhooks/booking
Headers: X-Webhook-Secret: <WEBHOOK_SECRET from .env>
Body: {"name": "...", "email": "...", "booking_time": "...", "service": "..."}
```

IRA detects hot leads with LLM qualification and notifies you via Telegram.

---

## Install IRA on Your Phone (PWA)

### 1. Set up Cloudflare Tunnel (no open ports)

```bash
curl -L --output cloudflared.deb \
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared.deb

cloudflared tunnel login
cloudflared tunnel create ira-private

cat > ~/.cloudflared/config.yml << 'EOF'
tunnel: ira-private
credentials-file: /root/.cloudflared/<TUNNEL_ID>.json

ingress:
  - hostname: ira.yourdomain.com
    service: http://localhost:3000
  - hostname: ira-api.yourdomain.com
    service: http://localhost:8000
  - service: http_status:404
EOF

cloudflared tunnel route dns ira-private ira.yourdomain.com
cloudflared tunnel route dns ira-private ira-api.yourdomain.com

sudo cloudflared service install
sudo systemctl enable --now cloudflared
```

### 2. Add to home screen

1. Open `https://ira.yourdomain.com` on your phone
2. **iPhone (Safari):** Share → Add to Home Screen
3. **Android (Chrome):** Menu → Add to Home Screen
4. IRA launches full-screen — no browser chrome, dark theme, instant load

The PWA includes a **Voice Mode shortcut** — tap it from your home screen to start a voice session immediately without opening the app manually.

---

## Project Structure

```
private-Jarvis/
└── supracloud-jarvis/
    ├── docker-compose.yml          ← 10 services
    ├── docker-compose.cloud.yml    ← 8×H100 cloud overlay
    ├── nginx/nginx.conf            ← TLS 1.3, CSP, LiveKit proxy
    ├── livekit/livekit.yaml        ← LiveKit server config (keys via env)
    ├── postgres/
    │   ├── init.sql                ← Base schema
    │   ├── 002_phase4.sql          ← Tasks, calendar, monitor state
    │   ├── 003_biometrics.sql      ← Voice profiles + audit table
    │   └── 004_memory_isolation_hnsw.sql  ← Per-user HNSW index
    ├── scripts/
    │   ├── setup.sh                ← One-command server setup
    │   └── verify.sh               ← Health check all services
    ├── frontend/
    │   ├── public/
    │   │   ├── manifest.json       ← PWA manifest (voice shortcut)
    │   │   └── icons/              ← SVG home-screen icons
    │   ├── app/
    │   │   ├── layout.tsx
    │   │   └── page.tsx            ← Mode routing, voice auto-connect
    │   └── components/
    │       ├── ChatInterface.tsx   ← SSE streaming, all mode toggles, media players
    │       ├── VoiceOrb.tsx        ← LiveKit voice, auto-connect, pulse animation
    │       ├── Sidebar.tsx         ← Mode selector, conversation history, backup
    │       └── StatusBar.tsx
    └── ira/
        ├── main.py                 ← FastAPI app, 17 routers registered
        ├── config.py               ← All env vars via Pydantic Settings
        ├── base_resume.md          ← Your resume in Markdown (edit with real content)
        ├── agents/
        │   ├── graph.py            ← LangGraph pipeline (10 specialist nodes)
        │   ├── supervisor.py       ← Query classifier + is_restricted_domain()
        │   ├── state.py            ← IRAState TypedDict
        │   ├── conversational.py   ← Grok-personality chat
        │   ├── researcher.py       ← Deep research agent
        │   ├── security.py         ← Threat tools (owner-only gate)
        │   ├── website.py          ← Website content management
        │   ├── creator.py          ← Meta-agent generator
        │   ├── executor.py         ← Sandboxed command execution
        │   ├── career.py           ← GitHub + Apify + resume tailoring
        │   ├── tutor.py            ← Socratic teaching agent
        │   ├── digital.py          ← OS + shell + browser agent
        │   ├── expert_mode.py      ← 5-parallel-agent Expert Mode
        │   ├── architect_agent.py  ← 5-agent evolution team
        │   ├── engineer_agent.py   ← 4-step engineering mode
        │   └── grok_personality.py ← Grok-style system prompt builder
        ├── api/routes/
        │   ├── chat.py             ← /chat/stream, /chat/expert, /chat/vision
        │   ├── image_gen.py        ← /image/generate, /image/edit
        │   ├── video_gen.py        ← /video/generate, /video/understand
        │   ├── audio_gen.py        ← /audio/generate, /audio/tts, /audio/transcribe
        │   ├── design_tools.py     ← /design/generate, /design/download/{id}
        │   ├── document_create.py  ← /document/create, /document/download/{id}
        │   ├── computer_use.py     ← /computer/use, /computer/screenshot
        │   ├── deep_research.py    ← /research/deep, /research/article
        │   ├── multimodal.py       ← /multimodal/analyse
        │   ├── architect.py        ← /architect/propose, /implement, /apply
        │   ├── voice.py            ← /voice/token, /voice/enroll, /voice/challenge
        │   ├── backup.py           ← /backup/list, /backup/create, /backup/restore
        │   ├── briefing.py         ← /briefing/morning
        │   ├── tasks.py            ← /tasks CRUD
        │   ├── webhooks.py         ← /webhooks/lead, /webhooks/booking
        │   ├── notifications.py    ← /notifications + /ws/notifications
        │   ├── agents.py           ← /agents list
        │   └── health.py           ← /health
        ├── memory/
        │   ├── store.py            ← HNSW vector search, per-user isolation
        │   └── embeddings.py       ← BGE-large-en-v1.5 (thread-safe lazy load)
        ├── voice/
        │   ├── agent.py            ← LiveKit agent (4h timeout, biometric check per utterance)
        │   ├── biometrics.py       ← ECAPA-TDNN speaker verification
        │   ├── stt.py              ← Faster-Whisper (scipy resampling, thread-safe)
        │   ├── tts.py              ← Kokoro sentence-streaming (thread-safe)
        │   └── language.py         ← Language detection
        ├── utils/
        │   ├── llm.py              ← 3-tier vLLM routing + timeout + retry
        │   ├── url_safety.py       ← SSRF + DNS-rebinding protection (shared)
        │   ├── browser_tools.py    ← Playwright headless + _is_safe_url()
        │   ├── file_utils.py       ← read_with_size_cap() (64KiB chunks)
        │   ├── security_tools.py   ← scan_threats(), initiate_lockdown()
        │   ├── security_alerts.py  ← notify() → Telegram HTML + email + WebSocket
        │   ├── search_tools.py     ← DuckDuckGo DeepSearch + X routing
        │   ├── x_search.py         ← X API v2 → twitterapi.io → DDG (country-aware)
        │   ├── auto_implement.py   ← git apply + commit pipeline (never auto-pushes)
        │   ├── career_tools.py     ← GitHub + Apify + resume generation
        │   ├── tutor_tools.py      ← Student code evaluator (Socratic hints)
        │   ├── os_tools.py         ← open_application() + run_terminal_command()
        │   ├── db.py               ← asyncpg connection pool
        │   └── redis_client.py     ← Async Redis client
        └── worker/
            ├── main.py             ← APScheduler worker entrypoint
            ├── scheduler.py        ← 8 cron jobs registered
            ├── briefing.py         ← Morning briefing generator
            ├── security_monitor.py ← nginx + SSH + CPU watchdog (60s)
            ├── self_healing.py     ← Health checks + automated remediation
            ├── backup.py           ← pg_dump + 7-day retention
            ├── business_monitor.py ← Lead/booking tracker
            ├── reminders.py        ← Reminder scheduler
            └── notifier.py         ← Email dispatcher
```

---

## API Reference (Key Endpoints)

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/auth/token` | Get JWT token |
| `POST` | `/api/v1/chat/stream` | Streaming chat (SSE) |
| `POST` | `/api/v1/chat/expert` | Expert Mode — 5 agents (SSE) |
| `POST` | `/api/v1/chat/vision` | Vision analysis (SSE) |
| `POST` | `/api/v1/image/generate` | Text-to-image (SSE) |
| `POST` | `/api/v1/image/edit` | Image editing (SSE) |
| `POST` | `/api/v1/video/generate` | Text-to-video (SSE) |
| `POST` | `/api/v1/video/understand` | Video analysis (SSE) |
| `POST` | `/api/v1/audio/generate` | Music/SFX generation (SSE) |
| `POST` | `/api/v1/audio/tts` | Text-to-speech (SSE) |
| `POST` | `/api/v1/audio/transcribe` | Speech-to-text (SSE) |
| `POST` | `/api/v1/design/generate` | HTML/Mermaid/SVG design (SSE) |
| `GET`  | `/api/v1/design/download/{id}` | Download design artefact |
| `POST` | `/api/v1/document/create` | PDF/DOCX/PPTX/XLSX (SSE) |
| `GET`  | `/api/v1/document/download/{id}` | Download document |
| `POST` | `/api/v1/computer/use` | Browser automation (SSE) |
| `POST` | `/api/v1/computer/screenshot` | Page screenshot |
| `POST` | `/api/v1/research/deep` | 5-round deep research (SSE) |
| `POST` | `/api/v1/research/article` | Article/blog generation (SSE) |
| `POST` | `/api/v1/multimodal/analyse` | Multi-modal fusion (SSE) |
| `POST` | `/api/v1/architect/propose` | Architect proposal (SSE) |
| `POST` | `/api/v1/architect/apply` | Apply diffs + commit |
| `GET`  | `/api/v1/voice/challenge` | Anti-replay challenge token |
| `GET`  | `/api/v1/voice/token` | LiveKit access token |
| `POST` | `/api/v1/voice/enroll` | Biometric voice enrolment |
| `POST` | `/api/v1/backup/create` | Manual backup |
| `GET`  | `/api/v1/backup/list` | List backups |
| `POST` | `/api/v1/backup/restore` | Restore from backup |
| `GET`  | `/health` | Service health check |

All streaming endpoints use **Server-Sent Events (SSE)**. Connect with `EventSource` or `fetch()` with `ReadableStream`.

---

## Environment Variables

Key variables to set in `.env` (full template in `.env.example`):

```env
# Identity
OWNER_NAME=Praveen Kumar Kamineti
IRA_ADMIN_PASSWORD=your_secure_password

# LLM
VLLM_FAST_URL=http://vllm-fast:8001/v1
VLLM_DEEP_URL=http://vllm-deep:8002/v1
VLLM_FAST_MODEL=qwen3-fast
VLLM_DEEP_MODEL=qwen3-deep
VLLM_REASONING_URL=              # optional

# Dev mode (CPU only)
DEV_MODE=false
OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
DEV_MODEL=qwen3:8b

# Notifications
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# External APIs (all optional)
REPLICATE_API_TOKEN=
TWITTER_BEARER_TOKEN=
X_FALLBACK_API_KEY=
APIFY_API_TOKEN=
GITHUB_TOKEN=

# Voice
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=
IRA_VOICE=af_bella               # or af_heart

# Backup
BACKUP_DIR=/backups
BACKUP_KEEP=7

# Timezone
BRIEFING_TIMEZONE=Asia/Kolkata
```

---

## Secrets Management

IRA uses [sops](https://github.com/getsops/sops) + [age](https://github.com/FiloSottile/age) for encrypted secrets.

### First-time setup
```bash
bash scripts/init-secrets.sh   # generates your age key
cp .env.example .env            # fill in your values
make secrets-encrypt            # creates .env.enc (safe to commit)
```

### On a new machine
```bash
# Copy your age key from backup:
mkdir -p ~/.config/sops/age && cp your-backup/keys.txt ~/.config/sops/age/
export SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt
make secrets-decrypt            # creates .env from .env.enc
```

### Editing secrets
```bash
make secrets-edit   # opens .env.enc in your editor, re-encrypts on save
```

---

## Author

**Praveenkumar**  
GitHub: [@Praveenkumar101508](https://github.com/Praveenkumar101508)  
Company: SupraCloud

---

*SupraCloud IRA — Private, Sovereign, Yours.*
