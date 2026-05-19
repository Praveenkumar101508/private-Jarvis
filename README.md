# SupraCloud IRA — Private Sovereign AI Assistant

> **IRA** — Intelligent Responsive Assistant  
> Built and maintained by **Praveenkumar**

A fully self-hosted, private AI assistant platform for SupraCloud. IRA runs entirely on your own hardware — no cloud APIs, no data leaving your server.

---

## 🧠 What IRA Can Do

| Capability | Description |
|------------|-------------|
| 💬 Multi-language Chat | English, Hindi, Tamil, Telugu, Kannada, Malayalam, German, French + more |
| 🔍 Deep Research | Long-form analysis, comparisons, summaries using Qwen 14B |
| 🔐 Security Guardian | Real-time nginx log monitoring, threat detection, alerts |
| 📊 Business Manager | Lead tracking, booking monitoring, business reports |
| 🤖 Agent Creator | Generates new LangGraph agents on demand |
| ⚙️ Executor | Sandboxed command execution with allowlist safety |
| 🎙️ Voice Interface | Full voice pipeline — speak to IRA, she speaks back |
| 📅 Calendar Sync | Cal.com integration, meeting reminders |
| 🔔 Proactive Alerts | Morning briefings, security alerts, reminders via Telegram + email |
| 🛡️ Biometric Gate | Voice-print authentication locks private data to the owner only |

---

## 🏗️ Architecture

```
                          User (Browser / Voice)
                                   │
                              [ nginx ]
                          TLS termination + proxy
                                   │
                    ┌──────────────┼──────────────┐
                    ▼              ▼               ▼
             [ Frontend ]    [ IRA API ]     [ LiveKit ]
             Next.js 14     FastAPI +        WebRTC voice
                            LangGraph        server
                                   │
                    ┌──────────────┼──────────────┐
                    ▼              ▼               ▼
             [ vLLM Fast ]  [ vLLM Deep ]   [ IRA Worker ]
             Llama 3.1 8B   Qwen 2.5 14B    APScheduler
             ~2s response   ~8s response    6 scheduled jobs
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
             conversational  researcher  security
             website         creator     executor
                               │
                          store_interaction → END
```

---

## ⚙️ Tech Stack

| Layer | Technology |
|-------|------------|
| API | FastAPI 0.115 + Python 3.11 |
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
| Reverse Proxy | nginx 1.27 (TLS 1.3, rate limiting) |
| Container | Docker Compose (10 services) |
| GPU Target | NVIDIA RTX A4500 20GB VRAM |

---

## 🚀 Quick Start (Server Deployment)

### Prerequisites
- Ubuntu 22.04+ (or any Linux)
- Docker + Docker Compose v2
- NVIDIA GPU with drivers + nvidia-container-toolkit
- 32GB+ RAM recommended

### Step 1 — Clone the repository
```bash
git clone -b claude/setup-private-session-1gF9a \
  https://github.com/Praveenkumar101508/private-Jarvis.git
cd private-Jarvis/supracloud-jarvis
```

### Step 2 — Run the setup script
```bash
bash scripts/setup.sh
```
This will:
- Check prerequisites (Docker, NVIDIA, openssl)
- Create `.env` from `.env.example` with auto-generated secrets
- Generate a self-signed TLS certificate for nginx
- Pull all Docker images (~15GB)

### Step 3 — Start all services
```bash
docker compose build
docker compose up -d
```

### Step 4 — Verify everything is healthy
```bash
bash scripts/verify.sh
```

### Step 5 — Open IRA
Visit `https://your-server-ip` in your browser.  
Default login: `admin` / (password you set during setup)

---

## 🛡️ Biometric Security Gate

IRA implements a **Dual-Role Clearance System**:

- **Public domain** (client calls, student tutoring, general questions) → anyone can ask
- **Restricted domain** (security logs, personal data, credentials, financials) → owner only

### Text requests
Admin JWT token → `is_owner = True` → full access

### Voice requests
ECAPA-TDNN voice embedding → cosine similarity ≥ 0.75 → full access

### Enrol your voice (first-time setup)
```bash
# Record 3+ WAV files of yourself speaking (16kHz mono, ≥3 seconds each)
curl -X POST https://your-domain/api/v1/voice/enroll \
  -H "Authorization: Bearer <your-jwt-token>" \
  -F "audio_files=@voice1.wav" \
  -F "audio_files=@voice2.wav" \
  -F "audio_files=@voice3.wav"
```

---

## 🔗 Webhook Integration (Receive Website Leads)

Point your website's contact form to:
```
POST https://your-domain/webhooks/lead
Headers: X-Webhook-Secret: <WEBHOOK_SECRET from .env>
Body: {"name": "...", "email": "...", "message": "...", "source": "website"}
```
IRA instantly notifies you via Telegram/WebSocket and qualifies the lead with AI.

---

## 📁 Project Structure

```
supracloud-jarvis/
├── docker-compose.yml          # All 10 services
├── nginx/nginx.conf            # TLS proxy + security headers
├── livekit/livekit.yaml        # Voice server config
├── postgres/
│   ├── init.sql                # Core schema (Phase 1)
│   ├── 002_phase4.sql          # Tasks, briefings, notifications
│   └── 003_biometrics.sql      # Voice profiles, audit log
├── scripts/
│   ├── setup.sh                # One-command setup
│   └── verify.sh               # Health verification
├── frontend/                   # Next.js 14 chat UI
│   ├── app/page.tsx
│   ├── components/ChatInterface.tsx
│   ├── components/VoiceButton.tsx
│   └── components/StatusBar.tsx
└── ira/                        # Python backend
    ├── main.py                 # FastAPI app
    ├── config.py               # All settings (env vars)
    ├── agents/
    │   ├── graph.py            # LangGraph pipeline
    │   ├── supervisor.py       # Routing + biometric gate
    │   ├── state.py            # Shared state type
    │   ├── conversational.py
    │   ├── researcher.py
    │   ├── security.py
    │   ├── website.py
    │   ├── creator.py
    │   └── executor.py
    ├── api/routes/
    │   ├── chat.py             # SSE streaming chat
    │   ├── voice.py            # LiveKit token + enrolment
    │   ├── webhooks.py         # Lead + booking intake
    │   ├── tasks.py
    │   ├── briefing.py
    │   ├── notifications.py
    │   └── health.py
    ├── memory/
    │   ├── store.py            # pgvector RAG
    │   └── embeddings.py       # BGE embeddings
    ├── voice/
    │   ├── agent.py            # LiveKit voice pipeline
    │   ├── biometrics.py       # ECAPA-TDNN speaker verification
    │   ├── stt.py              # Faster-Whisper STT
    │   └── tts.py              # Kokoro TTS
    └── worker/
        ├── scheduler.py        # APScheduler (6 jobs)
        ├── briefing.py         # Morning/evening briefings
        ├── security_monitor.py # Nginx log analysis
        ├── business_monitor.py # Lead/booking scanner
        ├── reminders.py        # Reminder delivery
        └── notifier.py         # Telegram + email + WebSocket
```

---

## 🔒 Security

- All secrets via environment variables — never hardcoded
- JWT HS256 authentication on all API endpoints
- nginx: TLS 1.3 only, HSTS, CSP, rate limiting
- PostgreSQL bound to `127.0.0.1` only — never exposed to internet
- Executor agent: allowlist-only command execution
- Biometric voice gate: ECAPA-TDNN cosine similarity threshold
- Admin password: bcrypt-hashed on first use

---

## 👤 Author

**Praveenkumar**  
GitHub: [@Praveenkumar101508](https://github.com/Praveenkumar101508)  
Company: SupraCloud

---

*SupraCloud IRA — Private, Sovereign, Yours.*
