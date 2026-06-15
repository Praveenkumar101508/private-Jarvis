# Changelog

All notable changes to SupraCloud IRA are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]
### Planned
- Multi-user support with per-user memory isolation
- Calendar write-back (Google Calendar + Cal.com)
- Persistent file storage (MinIO/S3)
- Mobile push notifications (beyond Telegram)
- TOTP two-factor authentication for admin login

---

## [1.0.0] — 2026-05

### Added — Core Platform
- FastAPI async backend with LangGraph hierarchical multi-agent routing
- 9-specialist agent graph: conversational, researcher, security, website, creator, executor, career, tutor, digital
- 3-tier vLLM inference routing: fast (Qwen3-8B), deep (Qwen3-14B), reasoning (DeepSeek-R1/Qwen3-32B)
- Server-Sent Events (SSE) streaming chat with token-by-token delivery
- Think Mode: step-by-step reasoning with collapsible `<think>` panel
- Expert Mode: 5 specialist agents run in parallel, debate, and synthesise a final answer
- Engineer Mode: the assistant-style 4-step code workflow (analyse → plan → diff → verify)
- Grok Mode: Grok-style personality with auto search and image generation

### Added — Memory & RAG
- PostgreSQL + pgvector persistent memory with BGE-large-en-v1.5 embeddings
- Semantic retrieval with HNSW index (cosine similarity, 0.6 threshold)
- Per-user memory isolation (user_id scoping on all embeddings)
- Background async embedding with GC-safe task references
- Weekly memory retention purge (90-day rolling window)
- LangGraph AsyncPostgresSaver for persistent conversation state

### Added — Voice Pipeline
- LiveKit WebRTC voice rooms with agent session management
- Faster-Whisper large-v3 multilingual STT
- Kokoro-82M ONNX TTS (af_bella voice, 1.05x speed)
- Silero VAD for turn detection
- Per-session voice rooms with 4-hour maximum session cap
- ECAPA-TDNN biometric speaker verification (SpeechBrain)
- Anti-replay challenge system for voice enrolment
- WAV format validation (16kHz/mono/16-bit enforcement)

### Added — Multimodal & Generation
- Image generation via Stable Diffusion WebUI or Replicate FLUX Schnell
- Image editing via InstructPix2Pix
- Vision analysis via Qwen3-VL (image upload + Q&A)
- Video generation and understanding via Replicate Wan2.1
- Audio/music generation via MusicGen, Bark, AudioLDM
- Native document creation: PDF (ReportLab), Word (python-docx), PowerPoint (python-pptx), Excel (openpyxl)
- Design tools: SVG/HTML UI mockup generation
- Deep research mode: 3-round iterative search with article synthesis
- Multi-modal fusion: combined image + audio + document analysis
- Computer use: Playwright-driven browser automation

### Added — Proactive Intelligence
- Morning (08:00) and evening (20:00) AI briefings via APScheduler
- Real-time WebSocket notification push
- Telegram and SMTP email notification channels
- Security monitoring: nginx log analysis for SQLi/XSS/path traversal
- SSH brute-force detection
- System health monitoring (CPU, memory, disk, Redis, DB)
- Automatic lockdown trigger on critical threat detection
- Self-healing agent: 60-second diagnostic + remediation cycle
- Business monitor: lead and booking event tracking
- Cal.com calendar sync (30-minute intervals)
- Reminder engine with cron recurrence support

### Added — Architect Evolution System
- 5-agent evolution team (Researcher, Critic, Executor, Creator, Supervisor)
- 12-hour background capability gap analysis
- Proposal + review + apply workflow
- git apply + commit pipeline with dry-run validation

### Added — Career Tools
- Resume tailoring against job descriptions
- LinkedIn and Indeed job board scraping via Apify
- GitHub repository analysis
- Cover letter generation
- Interview preparation mode

### Added — Infrastructure
- Docker Compose full-stack orchestration (9 services)
- nginx reverse proxy with TLS, rate limiting, security headers
- PostgreSQL 16 with pgvector + 4 schema migrations
- Redis 7 for caching, pub/sub, and session state
- LiveKit server (WebRTC)
- Daily pg_dump database backup with 7-day retention
- Cloud Docker Compose for 8×H100 deployment
- Next.js 14 PWA frontend with offline support
- JWT authentication with bcrypt, constant-time comparison
- Per-route slowapi rate limiting

### Security
- Biometric dual-role access gate (owner vs public)
- JWT tokens with 24-hour expiry
- Username enumeration prevention (dummy bcrypt timing)
- CORS locked to configured domain
- Content Security Policy headers
- Anti-replay challenge for voice enrolment
- 6-hour security event digest
- Auto-lockdown on critical threat detection

---

## How to update this file

When you add a feature, add an entry under `[Unreleased]` → `Added`.
When you fix a bug, add it under `Fixed`.
When you release a version: rename `[Unreleased]` to `[X.Y.Z] — YYYY-MM-DD` and create a new empty `[Unreleased]` section above it.
