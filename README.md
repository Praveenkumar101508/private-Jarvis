# SupraCloud IRA — Private Sovereign AI Assistant

> **IRA** — Intelligent Responsive Assistant  
> Built and maintained by **Praveenkumar**

A fully self-hosted, private AI assistant platform. IRA runs entirely on your own hardware — no cloud APIs, no data leaving your server. Phase 3 turns IRA into an **Active Threat Monitor and Mobile Bodyguard**: real-time security watchdog, Telegram push alerts to your phone, and a PWA accessible from anywhere via Cloudflare Tunnel.

---

## What IRA Can Do

| Capability | Description |
|------------|-------------|
| Multi-language Chat | English, Hindi, Tamil, Telugu, Kannada, Malayalam, German, French + more |
| Deep Research | Long-form analysis, comparisons, summaries using Qwen 14B |
| Security Bodyguard | Active threat monitoring — SSH brute-force, network scans, CPU spike detection |
| Network Scanner | `scan_threats()` — maps all external connections and classifies threat level |
| Panic Lockdown | `initiate_lockdown()` — voice-triggered killswitch with instant Telegram confirmation |
| Secure Messaging | `dispatch_secure_message()` — say "IRA, text my phone..." → lands in your Telegram |
| Business Manager | Lead tracking, booking monitoring, business reports |
| Agent Creator | Generates new LangGraph agents on demand |
| Executor | Sandboxed command execution with allowlist safety |
| Voice Interface | Full voice pipeline — speak to IRA, she speaks back (Kokoro af_bella) |
| Calendar Sync | Cal.com integration, meeting reminders |
| Proactive Alerts | Morning briefings, security alerts, reminders via Telegram + email |
| Biometric Gate | Voice-print authentication locks private data to the owner only |
| Mobile PWA | Installable on iPhone/Android — runs full-screen like a native app |
| Career Engine | GitHub analysis, LinkedIn/Indeed job scraping, auto-tailored resume generation |
| Supracloud Tutor | Socratic teaching mode — evaluates student code, asks leading questions, never spoon-feeds answers |
| Digital Brain | OS control (open VS Code, terminal), read-only shell commands, headless browser + page Q&A |

---

## Architecture

```
                    Phone (Telegram alerts + PWA app)
                                │  ▲
                    Cloudflare  │  │  push notifications
                    Tunnel      │  │
                                ▼  │
                          [ nginx ]
                      TLS termination + proxy
                                │
                 ┌──────────────┼──────────────┐
                 ▼              ▼               ▼
          [ Frontend ]    [ IRA API ]     [ LiveKit ]
          Next.js 14     FastAPI +        WebRTC voice
          PWA-ready      LangGraph        server
                                │
                 ┌──────────────┼──────────────┐
                 ▼              ▼               ▼
          [ vLLM Fast ]  [ vLLM Deep ]   [ IRA Worker ]
          Llama 3.1 8B   Qwen 2.5 14B    APScheduler
          ~2s response   ~8s response    6 scheduled jobs
                                         + Watchdog (60s)
                 │
       ┌─────────┴─────────┐
       ▼                   ▼
  [ PostgreSQL ]       [ Redis ]
  + pgvector RAG       cache + pub/sub
```

### LangGraph Agent Pipeline

```
START → retrieve_memory → classify → biometric_gate
         │                               │
         ▼                    ┌──────────┴──────────┐
     [RAG memory]             ▼ owner               ▼ public
                         [Specialist]          [access_denied]
                              │
                   ┌──────────┼──────────┐
                   ▼          ▼          ▼
            conversational  researcher  security ← bodyguard tools
            website         creator     executor
                              │
                         store_interaction → END
```

### Phase 4 — Career Automation Pipeline

```
User: "IRA, analyze the job at [LinkedIn URL] and tailor my resume"
  ↓
Career Agent
  ├─ analyze_my_codebase()     → GitHub API: top languages, project summaries
  ├─ scrape_job_posting(url)   → Apify: title, company, requirements, description
  └─ generate_tailored_resume() → Deep LLM: rewrites base_resume.md, saves tailored_resume.md
  ↓
IRA responds with match analysis + 3 interview talking points
```

### Phase 5 — Supracloud Tutor Mode

```
Frontend toggle: Assistant ↔ Tutor (UI shifts to indigo theme)
  ↓
Tutor Agent (all traffic when mode=tutor)
  ├─ evaluate_student_submission(code, topic) → private LLM critique
  │    Returns: correctness score, logic errors, Socratic hints
  └─ IRA speaks hints only — NEVER reveals the answer
```

### Phase 6 — Digital Robot Brain

```
User: "IRA, open VS Code"          → open_application("vscode") → subprocess
User: "IRA, run git status"        → run_terminal_command()     → allowlisted shell
User: [pastes URL in chat]         → browse_and_summarize_website() → Playwright + LLM
User: "IRA, what is their pricing" → headless Chromium extracts text → LLM answers
```

### Security Watchdog Loop (every 60 seconds)

```
run_security_scan()
  ├─ parse nginx access.log  → SQLi / XSS / path traversal / scanner UA / brute-force
  ├─ parse /var/log/auth.log → SSH failed logins (≥3 from same IP → alert)
  ├─ psutil system metrics   → CPU >90% → Telegram push (cryptominer warning)
  ├─ write to security_events table
  └─ if critical/high → notify() → Telegram + WebSocket + Email
```

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| API | FastAPI 0.115 + Python 3.11 |
| Career Tools | PyGithub + Apify Client + LLM resume tailoring |
| Browser Tools | Playwright 1.47 headless Chromium |
| OS Tools | Python subprocess (allowlisted read-only commands) |
| Agent Framework | LangGraph 0.2 + LangChain 0.3 |
| LLM Inference | vLLM (OpenAI-compatible) |
| Fast Model | Llama 3.1 8B Instruct AWQ (~2s) |
| Deep Model | Qwen 2.5 14B Instruct AWQ (~8s) |
| Embeddings | BGE-large-en-v1.5 (1024-dim, CPU) |
| Vector DB | PostgreSQL 16 + pgvector |
| Cache | Redis 7 |
| Voice STT | Faster-Whisper large-v3 (CPU) |
| Voice TTS | Kokoro-82M af_bella (24kHz) |
| Voice Transport | LiveKit WebRTC |
| Biometrics | SpeechBrain ECAPA-TDNN (CPU) |
| Frontend | Next.js 14 + TypeScript + Tailwind CSS |
| Mobile Access | Progressive Web App + Cloudflare Tunnel |
| Reverse Proxy | nginx 1.27 (TLS 1.3, rate limiting) |
| Container | Docker Compose (10 services) |
| GPU Target | NVIDIA RTX A4500 20GB VRAM |

---

## Deployment Modes

IRA supports three deployment configurations depending on available hardware and budget:

| Mode | Hardware | Models | Use Case |
|------|----------|--------|----------|
| **Full-Local (Recommended)** | NVIDIA RTX A4500 20GB+ | Qwen3-8B (fast) + Qwen3-14B (deep) | Maximum privacy — zero cloud calls |
| **Hybrid** | Any GPU / CPU | Local LLMs + selected cloud APIs | Use Replicate for images, local for chat |
| **Dev Mode** | Any machine (even CPU-only) | Ollama (qwen3:8b) | Local development without GPU |

### Full-Local Mode (Default)
Everything runs on your hardware. Set `DEV_MODE=false` in `.env`. vLLM serves two quantized models:
- **Fast**: `qwen3-fast` (8B) — chat, classification, ~2s latency
- **Deep**: `qwen3-deep` (14B) — research, code, ~8s latency
- **Reasoning** (optional): `qwen3-reasoning` (32B+) — Think Mode, DeepSearch

### Dev Mode (CPU Only)
Set `DEV_MODE=true` to route all LLM calls to a local Ollama instance. No GPU required.
```bash
ollama pull qwen3:8b     # recommended
# then set in .env:
DEV_MODE=true
DEV_MODEL=qwen3:8b
OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
```

### Known Limitations
- **Indic language voice** (Hindi, Tamil, etc.) — Whisper large-v3 accuracy varies; Indic speaker enrolment not tested
- **Biometric gate** — requires speechbrain + torch+cpu installed in `ira-voice` container; disabled if not installed
- **Recurring reminders** — require `croniter>=1.4` in `ira/requirements.txt`
- **Voice STT resampling** — requires `scipy>=1.14` for anti-aliasing; falls back to basic decimation without it

---

## Cloud-Dependent Features

The following features require external API keys. IRA works fully without them, but these features will be disabled or degraded:

| Feature | Required Key | Set in `.env` | Free Tier? |
|---------|-------------|--------------|------------|
| Image generation | Replicate | `REPLICATE_API_TOKEN` | Yes (limited) |
| Video generation | Replicate (Kling / Veo) | `REPLICATE_API_TOKEN` | No |
| Audio transcription (cloud) | Replicate (Whisper) | `REPLICATE_API_TOKEN` | Yes |
| X / Twitter search | X API v2 | `TWITTER_BEARER_TOKEN` | Yes (Basic) |
| X search fallback | twitterapi.io | `X_FALLBACK_API_KEY` | $5/month |
| LinkedIn job scraping | Apify | `APIFY_API_TOKEN` | Yes (limited) |
| GitHub repo analysis | GitHub API | `GITHUB_TOKEN` | Yes |
| Telegram alerts | Telegram Bot API | `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | Free |
| Email notifications | Any SMTP | `SMTP_HOST/USER/PASS/TO` | Varies |
| Calendar (Cal.com) | Cal.com API | `CALCOM_API_KEY` | Yes |
| Calendar (Google) | GCP service account | `GOOGLE_SERVICE_ACCOUNT_JSON` | Yes |

**Everything else** (chat, memory, research, security monitoring, briefings, voice, biometrics, architect, engineer mode, tutor, document creation) runs entirely on-premises.

---

## Quick Start (Server Deployment)

### Prerequisites
- Ubuntu 22.04+ (or any Linux / WSL2)
- Docker + Docker Compose v2
- NVIDIA GPU with drivers + nvidia-container-toolkit
- 32GB+ RAM recommended

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
Creates `.env`, auto-generates secrets, generates TLS cert, pulls images (~15GB).

### Step 3 — Build and start
```bash
docker compose build
docker compose up -d
```

### Step 4 — Verify
```bash
bash scripts/verify.sh
```

### Step 5 — Open IRA
Visit `https://your-server-ip`. Default login: `admin` / (password set during setup).

---

## Biometric Security Gate

IRA implements a **Dual-Role Clearance System**:

- **Public domain** — anyone can ask (general questions, research, chat)
- **Restricted domain** — owner only (security logs, credentials, personal data, financials)

### Text requests
Admin JWT token → `is_owner = True` → full access

### Voice requests
ECAPA-TDNN voice embedding → cosine similarity ≥ 0.75 → full access

### Enrol your voice
```bash
curl -X POST https://your-domain/api/v1/voice/enroll \
  -H "Authorization: Bearer <your-jwt>" \
  -F "audio_files=@voice1.wav" \
  -F "audio_files=@voice2.wav" \
  -F "audio_files=@voice3.wav"
```

---

## Phase 3: Bodyguard Mode & Mobile Access

### Telegram Alerts

Set these two values in your `.env`:
```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

IRA will push to your phone instantly for:
- SSH brute-force attempts (≥3 failures from one IP)
- CPU spike >90% (cryptominer warning)
- SQL injection / XSS patterns detected
- Critical unresolved security events
- Lockdown initiated / lifted

### Career Automation Commands

| Command | Action |
|---------|--------|
| "IRA, analyze my GitHub" | Scans 3 most recent repos, language stats, project summaries |
| "IRA, scrape [LinkedIn URL]" | Extracts job title, company, requirements |
| "IRA, tailor my resume for this job" | Rewrites bullet points to match scraped job description |
| "IRA, prep me for the interview at [URL]" | Full pipeline: scrape + analyze + generate |

> **Setup:** Add `APIFY_API_TOKEN` (free at apify.com) and `GITHUB_TOKEN` to your `.env`.  
> Create `ira/base_resume.md` with your resume content in Markdown format.

### Tutor Mode Commands

Toggle the **🎓 Tutor** button in the header to enter teaching mode (UI turns indigo).

| Student says | IRA does |
|--------------|----------|
| "I don't understand Docker" | Gives a metaphor + asks 1 leading question |
| "Here is my code: \`\`\`..." | Privately evaluates it, returns Socratic hints |
| "Just tell me the answer" | Refuses warmly, asks another leading question |

### Digital Brain Commands

| Command | Action |
|---------|--------|
| "IRA, open VS Code" | Launches VS Code in the current directory |
| "IRA, run git status" | Executes and reads back the output |
| "IRA, check docker ps" | Shows running containers |
| Paste any URL in chat | Headless browser loads it, LLM answers your question about it |

### Voice Security Commands

Say any of these to IRA:

| Voice Command | Action |
|---------------|--------|
| "IRA, scan for threats" | Runs network scan, reports external connections |
| "IRA, lock down the system" | Engages lockdown, sends Telegram confirmation |
| "IRA, lift lockdown" | Restores normal operations |
| "IRA, text my phone: I'm heading out" | Dispatches message to your Telegram |
| "IRA, engage lockdown mode and monitor all traffic" | Full bodyguard mode |

### Install IRA on Your Phone (PWA)

#### 1. Set up Cloudflare Tunnel (no open ports — secure)

```bash
# Install cloudflared on your Linux/WSL machine
curl -L --output cloudflared.deb \
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared.deb

# Authenticate (opens browser once)
cloudflared tunnel login

# Create the tunnel
cloudflared tunnel create ira-private

# Configure (~/.cloudflared/config.yml)
cat > ~/.cloudflared/config.yml << 'EOF'
tunnel: ira-private
credentials-file: /root/.cloudflared/<YOUR_TUNNEL_ID>.json

ingress:
  - hostname: ira.yourdomain.com
    service: http://localhost:3000
  - hostname: ira-api.yourdomain.com
    service: http://localhost:8000
  - service: http_status:404
EOF

# Add DNS records
cloudflared tunnel route dns ira-private ira.yourdomain.com
cloudflared tunnel route dns ira-private ira-api.yourdomain.com

# Run as a background service
sudo cloudflared service install
sudo systemctl enable --now cloudflared
```

#### 2. Add IRA to your home screen

1. Open `https://ira.yourdomain.com` on your phone (Safari on iPhone, Chrome on Android)
2. Tap **Share → Add to Home Screen** (iPhone) or **Menu → Add to Home Screen** (Android)
3. IRA appears as a full-screen app — no browser chrome, dark theme, instant load

---

## Security Architecture

| Layer | Protection |
|-------|------------|
| Network | Cloudflare Tunnel — no open ports exposed to the internet |
| TLS | nginx TLS 1.3 only, HSTS, CSP headers |
| Auth | JWT HS256 on all API endpoints + bcrypt admin password |
| Biometrics | ECAPA-TDNN voice gate (cosine similarity ≥ 0.75) |
| Database | PostgreSQL bound to 127.0.0.1 only |
| Executor | Allowlist-only command execution, 30s timeout, no network |
| Watchdog | 60s scan cycle — nginx logs, SSH logs, system metrics |
| Alerts | Direct Telegram push for SSH attacks and CPU spikes |

---

## Webhook Integration

Point your website contact form to:
```
POST https://your-domain/webhooks/lead
Headers: X-Webhook-Secret: <WEBHOOK_SECRET from .env>
Body: {"name": "...", "email": "...", "message": "...", "source": "website"}
```

---

## Project Structure

```
supracloud-jarvis/
├── docker-compose.yml
├── nginx/nginx.conf
├── livekit/livekit.yaml
├── postgres/
│   ├── init.sql
│   ├── 002_phase4.sql
│   └── 003_biometrics.sql
├── scripts/
│   ├── setup.sh
│   └── verify.sh
├── frontend/
│   ├── public/
│   │   ├── manifest.json          ← PWA manifest (new)
│   │   └── icons/                 ← App icons for home screen
│   ├── app/
│   │   ├── layout.tsx             ← PWA meta tags (updated)
│   │   └── page.tsx
│   ├── components/
│   │   ├── ChatInterface.tsx
│   │   ├── VoiceButton.tsx
│   │   └── StatusBar.tsx
│   └── next.config.js             ← PWA headers (updated)
└── ira/
    ├── main.py
    ├── config.py
    ├── base_resume.md             ← Your resume in Markdown — edit with real details (new)
    ├── agents/
    │   ├── graph.py               ← career, tutor, digital agents registered (updated)
    │   ├── supervisor.py          ← career/tutor/digital/URL keyword routing (updated)
    │   ├── state.py
    │   ├── security.py            ← Bodyguard tools + updated system prompt (updated)
    │   ├── career.py              ← GitHub + Apify + resume tailoring agent (new)
    │   ├── tutor.py               ← Socratic teaching agent (new)
    │   ├── digital.py             ← OS control + headless browser agent (new)
    │   ├── conversational.py
    │   ├── researcher.py
    │   ├── website.py
    │   ├── creator.py
    │   └── executor.py
    ├── api/routes/
    │   ├── chat.py                ← mode field, tutor override, career/digital graph routing (updated)
    │   ├── voice.py
    │   ├── webhooks.py
    │   ├── tasks.py
    │   ├── briefing.py
    │   ├── notifications.py
    │   └── health.py
    ├── memory/
    │   ├── store.py
    │   └── embeddings.py
    ├── voice/
    │   ├── agent.py               ← VAD tuned for instant interruption (updated)
    │   ├── biometrics.py
    │   ├── stt.py
    │   └── tts.py
    ├── utils/
    │   ├── db.py
    │   ├── llm.py
    │   ├── redis_client.py
    │   ├── security_alerts.py     ← Sync Telegram push utility (new)
    │   ├── security_tools.py      ← scan_threats / lockdown / dispatch (new)
    │   ├── career_tools.py        ← GitHub / Apify / resume tailoring (new)
    │   ├── tutor_tools.py         ← Student code evaluator with Socratic hints (new)
    │   ├── os_tools.py            ← open_application / run_terminal_command (new)
    │   └── browser_tools.py       ← Playwright headless browse_and_summarize (new)
    └── worker/
        ├── scheduler.py
        ├── briefing.py
        ├── security_monitor.py    ← SSH log monitoring + CPU alerts (updated)
        ├── business_monitor.py
        ├── reminders.py
        └── notifier.py
```

---

## Author

**Praveenkumar**  
GitHub: [@Praveenkumar101508](https://github.com/Praveenkumar101508)  
Company: SupraCloud

---

*SupraCloud IRA — Private, Sovereign, Yours.*
