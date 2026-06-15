# IRA — Local Setup (Windows, no Docker, private, Ollama 14B)

Run IRA fully locally on the Shadow PC (Windows, NVIDIA RTX A4500 20 GB) with
**no Docker**, using **Ollama** for inference and a **14B** model. Auth and the
biometric gate stay **ON** (this is not dev mode). The heavy Docker/vLLM/nginx
stack is preserved under [`future-scale/`](future-scale/README.md) for the
future scale-up.

---

## Prerequisites

Install these once (the setup script checks each and prints hints):

| Component | Notes |
|-----------|-------|
| **Ollama** | https://ollama.com/download/windows — provides the local LLM at `localhost:11434` |
| **PostgreSQL 16 + pgvector** | https://www.postgresql.org/download/windows/ — the `vector` extension must be installable |
| **Memurai** (Redis for Windows) | https://www.memurai.com/get-memurai — drop-in Redis at `localhost:6379` (IRA requires it) |
| **Python 3.11+** | https://www.python.org/downloads/ |
| **Node.js LTS** | https://nodejs.org/ — for the Next.js frontend |

---

## 1. One-time setup

From the `supracloud-jarvis/` folder:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup-windows.ps1
```

This will:
1. Check the prerequisites above.
2. `ollama pull qwen3:14b` (the local chat model — all tiers map to it on 20 GB).
3. Create the `jarvis` role + `jarvis_db` database and `CREATE EXTENSION vector`.
4. Generate `.env` with `LLM_BACKEND=ollama`, localhost hosts, and randomly
   generated secrets (note the generated `IRA_ADMIN_PASSWORD` — it's your login).
5. Create a Python `.venv` and install `ira/requirements.txt`; run `npm install`
   in `frontend/`.

> **Embeddings:** stay on local `sentence-transformers` (`BAAI/bge-large-en-v1.5`,
> 1024-dim) — matching the `vector(1024)` DB column. The first run downloads the
> ~1.3 GB model and caches it. **Do not** swap the embedding model — it changes
> the vector dimension and breaks the memory DB.

### Frontend env (gitignored — create it)

`frontend/.env.local` is gitignored, so a fresh clone won't have it. Create it:

```
IRA_API_INTERNAL_URL=http://localhost:8000
```

(The browser already reaches the API via `next.config.js` rewrites; this file is
for Next.js SSR.)

---

## 2. Start everything

Make sure Ollama, PostgreSQL, and Memurai are running, then:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run-local.ps1
```

It pre-flights Ollama/Postgres/Memurai and launches the API, worker, and frontend
each in its own window.

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| API | http://localhost:8000  (OpenAPI docs at `/docs`) |
| Ollama | http://localhost:11434 |

On API startup you should see logs like:
```
PostgreSQL pool ready
migrations: all pending migrations applied
Redis connection ready
IRA is online. Good morning.
```

A chat message flows: **browser → :3000 → (rewrite) → API :8000 → supervisor →
Ollama :11434 (qwen3:14b) → memory saved with your user_id → streamed reply.**
No Docker, no vLLM.

---

## Switching the model

All tiers point at `OLLAMA_MODEL_*` in `.env`. To use a different local model:
```
ollama pull <tag>
# then in .env:
OLLAMA_MODEL_FAST=<tag>
OLLAMA_MODEL_DEEP=<tag>
OLLAMA_MODEL_REASONING=<tag>
```
Check Ollama's library for the current best 14B tag — they change often.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Ollama not responding on :11434` | Start Ollama (tray app) or run `ollama serve`. Verify: `curl http://localhost:11434/api/tags`. |
| Chat errors: model not found | `ollama pull qwen3:14b` (or set `OLLAMA_MODEL_*` to a model you have, e.g. `ollama list`). |
| `CREATE EXTENSION vector` fails | pgvector isn't installed for your PostgreSQL. Install the pgvector build/package, then re-run setup. |
| API exits at `Redis connection ready` step | Memurai isn't running. `Get-Service Memurai*` → `Start-Service`. IRA requires Redis at `localhost:6379`. |
| `Address already in use` :8000 / :3000 | Another process owns the port. `Get-NetTCPConnection -LocalPort 8000` to find it, or pass `-ApiPort 8001` to `run-local.ps1`. |
| First chat is slow | The embedding model (~1.3 GB) downloads on first use and the 14B loads into VRAM. Subsequent calls are fast. |
| Frontend SSR hits `ira-api:8000` | Create `frontend/.env.local` with `IRA_API_INTERNAL_URL=http://localhost:8000`. |

---

## What was verified vs. what to confirm on the Shadow PC

**Verified during migration:**
- The Ollama engine path works end-to-end: a live `POST http://localhost:11434/v1/chat/completions`
  (the exact OpenAI-compatible call `ira/utils/llm.py` makes, with the dummy
  `ollama` key) returned a valid completion — **Ollama, no Docker, no vLLM**.
- `LLM_BACKEND=ollama` routes every tier to `localhost:11434` while keeping
  auth/biometrics on (`_use_ollama()` is independent of `dev_mode`).
- Embedding dimension (1024) matches the `vector(1024)` schema column.
- Config and LLM modules parse cleanly.

**Confirm on the Shadow PC (could not be fully run during migration):**
- PostgreSQL 16 + **pgvector** installed; migrations apply on first boot.
- **Memurai** running at `localhost:6379`.
- `ollama pull qwen3:14b` completed (only `gemma2` was present on the dev box).
- `pip install -r ira/requirements.txt` + first-run `sentence-transformers` download.
- `frontend/` `npm install` and `npm run dev`.
- One real end-to-end chat through the UI, confirming a memory row is written
  with the correct `user_id`.
