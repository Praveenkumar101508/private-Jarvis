# SupraCloud IRA — Repository Inventory

_Phase 1 discovery snapshot. Branch audited: `supracloud_ira` (commit `4869034`)._

## Quick facts

| Item | Value |
| --- | --- |
| Project | SupraCloud IRA — local-first personal AI assistant |
| Maintainer | Praveen Kamineti (Praveen Kumar) |
| Backend | Python 3.11/3.12 · FastAPI 0.115 · LangGraph 0.2.73 · PostgreSQL + pgvector · Redis |
| Frontend | Next.js 14 (App Router) · React 18 · Tailwind CSS 3.4 · Zustand · TypeScript 5 |
| Mobile | Expo (React Native) PWA companion, optional |
| Inference | Ollama-native local models (Qwen3 tiers) + Cortex bridge; legacy vLLM path dormant |
| Package managers | pip (`requirements.txt` / `requirements-test.txt`), npm (`package-lock.json`) |
| Tests | pytest — 115 test files, 915 passed / 11 skipped locally |
| CI | GitHub Actions: `test.yml` (full suite + security checks), `ci.yml` (prod-deps resolution gate) |
| Python files | 289 (excluding vendor/third-party) |

## Directory tree (summary)

```
.
├─ README.md / ARCHITECTURE.md / SECURITY.md / CHANGELOG.md / RELEASE.md   # public docs
├─ CLAUDE.md / IRA_INTEGRATION.md / AGENTS.md / MERGE_PLAN.md   # internal working briefs (see audit)
├─ assets/                 # ira-banner.svg, ira-demo.svg (README art)
├─ docs/                   # implementation/verification reports (+ this audit set)
├─ security/               # Bumblebee scan outputs (ndjson) + README
├─ third_party/            # bumblebee, agency-agents — upstream LICENSE + NOTICE (KEEP)
└─ supracloud-jarvis/      # application root (historical directory name)
   ├─ .env.example         # 205-line documented env template, placeholder-only
   ├─ docker-compose.{portable,cloud,test}.yml · Makefile · start-ira.ps1
   ├─ frontend/            # Next.js 14 app (app/, components/, lib/)
   ├─ ira/                 # main Python package (below)
   ├─ mobile/              # Expo companion app
   ├─ portable/            # USB/portable profile: master password, health check, start scripts
   ├─ postgres/            # init.sql + migrations (pgvector, biometrics)
   ├─ livekit/             # legacy LiveKit voice server config
   ├─ scripts/             # setup/verify/harden scripts (bash + PowerShell)
   ├─ future-scale/        # cloud-scale docker/nginx blueprints (dormant)
   ├─ cortex-vendor/       # CHECKSUMS.txt + README only (binary vendored out-of-repo)
   └─ third_party/         # caldav, droidclaw NOTICE files (KEEP)
```

## The `ira` Python package

| Module | Contents | Role |
| --- | --- | --- |
| `main.py` (488) | FastAPI app factory, lifespan, CORS, rate limiter | entry point |
| `config.py` (591) | pydantic-settings `Settings`, safety validators (DEV_MODE × domain × bind-host) | configuration |
| `router.py` (60) | routing façade | brain routing |
| `cortex_bridge.py` (179) | anti-corruption layer to the local Cortex reasoning engine | bridge |
| `agents/` (24 files) | LangGraph graph, supervisor, conversational, researcher, engineer, architect, executor, security, career, tutor, digital, website, expert-mode, strategy, reflexion | specialist agents |
| `api/routes/` (33 files) | chat (SSE), voice, health, backup, notes, calendar, research, mobile, webhooks, totp, … | HTTP surface |
| `api/middleware/` | JWT auth, token revocation | auth |
| `reasoning/` | model_router, model_profiles, model_availability, answer_policy, answer_verifier, api_consent, memory_context, model_system_prompts, backends | model-routing + answer-quality layer |
| `research/` | deep_research_engine | multi-round sovereign web research |
| `channels/` | web, search, rss, github, youtube | fetch channels (sanitized) |
| `actions/` | email_triage (IMAP), calendar_dav (CalDAV), notes, drafting, android_actuator/pairing (flag-gated) | local-first actions |
| `memory/` | store, embeddings (BGE), reranker, life_graph, decision_journal | memory layer |
| `voice/` | agent, wakeword, biometrics (ECAPA), challenge, STT/TTS glue | voice layer |
| `worker/` (14 files) | scheduler, briefing, heartbeat, security_monitor, self_healing, backup, reminders, mobile push | background workers |
| `security/` + `utils/` | owner_gate, net_safety (SSRF), prompt_safety, cmd_safety, account_lockout, canary, approval | security utilities |
| `skills/` (12 dirs) | per-persona SKILL.md + code | persona layer |
| `tests/` (115 files) | unit + adversarial (prompt injection, SSRF, owner gate, gate consistency, no-plaintext-secrets) | test suite |

## Frontend modules

- `app/layout.tsx` — metadata, PWA tags; `app/page.tsx` — login + shell; `app/globals.css`
- `components/` — ChatInterface (SSE streaming chat, expert mode, think mode, attachments),
  Sidebar (modes, backup/restore), StatusBar, VoiceConsole, VoiceOrb, DemoModeBanner, PWARegister
- `lib/api.ts`, `lib/store.ts` (Zustand: auth/UI/chat stores)

## Security & config files

- `supracloud-jarvis/.env.example` — placeholder-only (`CHANGE_ME_*`), documents every variable
- `portable/demo.env.example`, `portable/master_password.py` — portable profile secrets handling
- `.github/workflows/test.yml` — suite + no-DEV_MODE auth tests + AST no-push check + secrets check
- `.github/workflows/ci.yml` — prod dependency resolution gate
- `security/*.ndjson` — Bumblebee scan results (read-only records)

## Generated / vendor files — do not hand-edit

- `supracloud-jarvis/frontend/package-lock.json`, `frontend/node_modules/` (ignored)
- `supracloud-jarvis/cortex-vendor/` (checksums of the vendored Cortex binary)
- `third_party/**` and `supracloud-jarvis/third_party/**` — upstream LICENSE/NOTICE (legal, keep verbatim)
- `security/*.ndjson` — scanner output
- `__pycache__/` directories (ignored)

## How the system works (one paragraph)

A request enters through the Next.js UI (or voice/mobile), hits the FastAPI gateway, and flows
through the LangGraph pipeline: retrieve ranked memory → classify and route to a specialist
agent → owner/biometric gate → the agent answers using the local model router (Ollama tiers via
the Cortex bridge, all bound to localhost) → rule-based answer verification → the interaction is
stored and embedded for future recall. External APIs are off by default behind an explicit
consent gate (`IRA_ALLOW_EXTERNAL_API=false`); destructive actions (email send, calendar write,
delete) require explicit human confirmation; background workers handle briefings, monitoring,
self-healing, and backups.

## Branches (at audit time)

| Branch | Status |
| --- | --- |
| `supracloud_ira` | default working branch — 96 commits, all history consolidated here |
| `ira` | intentional legacy-codebase archive (1 unique commit: `8ad11f8`) |
| `v2-portable-demo`, 6 × `claude/*` | fully merged into `supracloud_ira` (0 unique commits each) — see `docs/BRANCH_CLEANUP_REPORT.md` |
