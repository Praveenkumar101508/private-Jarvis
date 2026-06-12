# CLAUDE.md — read this first

This repo merges **Hermes** (the agent engine, `hermes-agent==0.15.2`) with **IRA**
(the SupraCloud product on top). Full plan: **`MERGE_PLAN.md`**.
This file is **ground truth** — where it conflicts with `MERGE_PLAN.md`, this file wins.

## Architecture in one line
Hermes runs **out-of-process** as a native-Windows CLI. IRA reaches the full agent through
**one bridge file** by shelling out to **`hermes -z`** (one-shot), which runs against LOCAL
Ollama configured in Hermes' own `config.yaml`. Hermes is **never installed into IRA's venv**
— its hard pins conflict with IRA's (see rule 3).

> ⚠️ **CORRECTION (verified against installed hermes-agent 0.15.2, 2026-06-11):** 0.15.2 ships
> **no** local, key-gated, OpenAI-compatible gateway on `:8642` and **no** `API_SERVER_KEY`
> (`hermes gateway` = messaging; `hermes proxy` = cloud-only). The earlier "HTTP gateway on
> :8642" design here is OBSOLETE — the bridge is now a **`hermes -z` subprocess**. Hermes
> config lives at `%LOCALAPPDATA%\hermes\config.yaml` (NOT `~/.hermes/`), nested under `model:`.
> Because `hermes -z` can't resume a per-conversation session, **thread memory is IRA-owned**
> (chat `_hermes_route` loads recent Postgres turns as context + persists each turn) — which
> refines rule 5 below.

## Non-negotiable rules
1. **Never edit Hermes core** or anything under `supracloud-jarvis/hermes-vendor/`. Extend ONLY via skills, subagents, MCP, and config. Hermes is pinned (`hermes-agent==0.15.2`) and runs in its OWN native install — not IRA's venv.
2. **ALL IRA→Hermes calls go through `supracloud-jarvis/ira/hermes_bridge.py` only** — a `hermes -z` SUBPROCESS wrapper (stdlib only; no `openai`/`hermes` import). Nothing else in IRA touches Hermes. (Engine-swap exit hatch: rewrite only this file.)
3. **Do NOT add `hermes-agent` to `ira/requirements.txt`.** It hard-pins `openai==2.24.0`, `pydantic==2.13.4`, `croniter==6.0.0`, `httpx`, `requests`, `tenacity` — all conflict with IRA's pins, and IRA's `langchain-openai` needs `openai 1.x`. Proven `pip install` ResolutionImpossible. The bridge uses IRA's EXISTING `openai`/`httpx` over HTTP — no new dependency.
4. Secrets (incl. `API_SERVER_KEY`) live in **env**, never in the repo. Keep the gateway bound to `127.0.0.1`.
5. **Postgres = business data only.** Memory/recall belongs to Hermes.

## Model backend: Ollama (NOT vLLM) — verified on this machine 2026-06-03
Shadow PC (`SHADOW-CR4M2J8D`, RTX A4500 20 GB). Docker daemon not running, WSL v1 (no CUDA), vLLM can't run native on Windows → **Ollama** (0.24.0, `:11434`, OpenAI-compatible). Pulled: `qwen3:8b`, `qwen3:14b`.
- `~/.hermes/config.yaml`: `provider: custom`, `base_url: http://localhost:11434/v1`, `default: qwen3:8b` (fast), `context_length: 65536`, `ollama_num_ctx: 65536` (Hermes needs ≥64K; Ollama defaults low).
- **Deep model `qwen3:14b` @ 64K FITS (~12 GB VRAM)** with KV-cache quant — user env `OLLAMA_FLASH_ATTENTION=1` + `OLLAMA_KV_CACHE_TYPE=q8_0` (set). Switch `default` to `qwen3:14b` for deep; per-request fast/deep selection is a later enhancement (the gateway serves one model at a time).

## Hermes install (native Windows, no Docker) — pinned 0.15.2
`iex (irm https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.ps1)` then
`& "%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe" -m pip install --upgrade hermes-agent==0.15.2`
(install.ps1's git-main is 0.15.1; pin to the PyPI release 0.15.2.) Installs under `%LOCALAPPDATA%\hermes`; `hermes gateway` runs natively on `127.0.0.1:8642`.
- **Persistence (no admin):** Startup launcher `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\ira-hermes-gateway.vbs` auto-starts the gateway hidden at logon (scheduled tasks need admin here). Start now: run that .vbs or `hermes gateway`.

## Reasoning skills vs the agentic gateway (Phase-6 note)
The gateway runs the FULL Hermes agent (files/shell/web tools). IRA's Option-A skills are reasoning-only (IRA runs the tools), so `skills/_common.run_skill` injects a no-tools directive. The model still sometimes over-reaches into a tool call (notably the security persona → tries to read `/var/log/auth.log`). Constraining/stripping the gateway toolset for reasoning skills is a **Phase-6** task.

## Bridge shape (Phase 2 reference — HTTP client, not an import)
```python
from openai import OpenAI          # IRA already depends on openai==1.54.4 — no new dep
client = OpenAI(base_url=os.environ["IRA_HERMES_URL"],   # http://127.0.0.1:8642/v1
                api_key=os.environ["IRA_HERMES_KEY"])     # = Hermes API_SERVER_KEY
r = client.chat.completions.create(model="hermes-agent",
                                   messages=[{"role": "user", "content": prompt}])
text = r.choices[0].message.content
```
(Per-tenant memory later: pass an `X-Hermes-Session-Key` header — the Phase 5 isolation hook.)

## Ground truth about THIS repo (verified against the code, 2026-06-03)
- **Git root** = repo top (`private-Jarvis-main`). Open Claude Code HERE; paths are relative to it. App code under **`supracloud-jarvis/ira/`**.
- **`requirements.txt` is at `supracloud-jarvis/ira/requirements.txt`** — none at the `supracloud-jarvis/` root. `.github/` lives at the git root (CI `working-directory: supracloud-jarvis/ira`; Dependabot `directory: /supracloud-jarvis/ira`).
- **Agents** (LangGraph today) at `supracloud-jarvis/ira/agents/`: `security.py, tutor.py, career.py, researcher.py, creator.py, website.py, conversational.py, digital.py, executor.py, expert_mode.py`, plus **`engineer_agent.py`, `architect_agent.py`** (the `_agent` suffix is on those two ONLY). `supervisor.py, graph.py, state.py` = the LangGraph router we RETIRE at the end.
- **Overlay home**: add `ira/hermes_bridge.py`, `ira/skills/`, `ira/subagents/` alongside existing code. Leave `ira/voice/`, `ira/config/`, `ira/memory/`, `ira/tests/` in place.

## Security ground truth (verified in code — wording matters)
- **Biometric gate** (`ira/voice/biometrics.py`): **fails CLOSED.** `is_owner_authenticated()` returns `False` on empty/sub-1s audio, no enrolled profile, model failure, or similarity < 0.75 (audit-logged). The function is half the story — the **router-level** "block non-owner on restricted domains" is the real Phase 4 check. **Do NOT rewrite the gate.**
- **Self-modification / "auto-deploy"** (`ira/utils/auto_implement.py`): **NO remote push** ("remote sync intentionally absent" — verified). A **human-gated local** pipeline exists: `git apply` → `git commit` → `docker compose restart`, triggered ONLY by an explicit `architect apply` (`is_apply_trigger`, `chat.py:311`, behind `pending_apply`). Accurate wording: **"gated local commit/restart, no remote push"** — NOT "no deploy path." Keep it gated; add a regression test.

## Workflow
Run `MERGE_PLAN.md` Part 6 prompts **one at a time, in order**. After each: **full report** (files changed + each acceptance-criterion result) → **commit to `merge/hermes-overlay`** (a remote push needs the owner's explicit go-ahead) → **STOP** for review. Never run two prompts back to back. When in doubt, ASK — never guess at scope. (Dev-backup commits to your own review branch are distinct from the IRA agent's runtime self-modification, which never pushes — Guardrail 5.)
