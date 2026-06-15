# AGENTS.md — read this first

This repo merges **Cortex** (the agent engine, `hermes-agent==0.15.2`) with **IRA**
(the SupraCloud product on top). Full plan: **`MERGE_PLAN.md`**.
This file is **ground truth** — where it conflicts with `MERGE_PLAN.md`, this file wins.

## Architecture in one line
Cortex runs **out-of-process** as a native-Windows CLI. IRA reaches the full agent through
**one bridge file** by shelling out to **`cortex -z`** (one-shot), which runs against LOCAL
Ollama configured in Cortex' own `config.yaml`. Cortex is **never installed into IRA's venv**
— its hard pins conflict with IRA's (see rule 3).

> ⚠️ **CORRECTION (verified against installed hermes-agent 0.15.2, 2026-06-11):** 0.15.2 ships
> **no** local, key-gated, OpenAI-compatible gateway on `:8642` and **no** `API_SERVER_KEY`
> (`cortex gateway` = messaging; `cortex proxy` = cloud-only). The earlier "HTTP gateway on
> :8642" design here is OBSOLETE — the bridge is now a **`cortex -z` subprocess**. Cortex
> config lives at `%LOCALAPPDATA%\cortex\config.yaml` (NOT `~/.cortex/`), nested under `model:`.
> Because `cortex -z` can't resume a per-conversation session, **thread memory is IRA-owned**
> (chat `_cortex_route` loads recent Postgres turns as context + persists each turn) — which
> refines rule 5 below.

## Non-negotiable rules
1. **Never edit Cortex core** or anything under `supracloud-jarvis/cortex-vendor/`. Extend ONLY via skills, subagents, MCP, and config. Cortex is pinned (`hermes-agent==0.15.2`) and runs in its OWN native install — not IRA's venv.
2. **ALL IRA→Cortex calls go through `supracloud-jarvis/ira/cortex_bridge.py` only** — a `cortex -z` SUBPROCESS wrapper (stdlib only; no `openai`/`cortex` import). Nothing else in IRA touches Cortex. (Engine-swap exit hatch: rewrite only this file.)
3. **Do NOT add `hermes-agent` to `ira/requirements.txt`.** It hard-pins `openai==2.24.0`, `pydantic==2.13.4`, `croniter==6.0.0`, `httpx`, `requests`, `tenacity` — all conflict with IRA's pins, and IRA's `langchain-openai` needs `openai 1.x`. Proven `pip install` ResolutionImpossible. The bridge uses IRA's EXISTING `openai`/`httpx` over HTTP — no new dependency.
4. Secrets (incl. `API_SERVER_KEY`) live in **env**, never in the repo. Keep the gateway bound to `127.0.0.1`.
5. **Postgres = business data only.** Memory/recall belongs to Cortex.

## Model backend: Ollama (NOT vLLM) — verified on this machine 2026-06-15
Shadow PC (`SHADOW-CR4M2J8D`, RTX A4500 20 GB). Docker daemon not running, WSL v1 (no CUDA), vLLM can't run native on Windows → **Ollama** (0.24.0, `:11434`, OpenAI-compatible). Pulled: `qwen3:8b`, `qwen3:14b`.
- `~/.cortex/config.yaml`: `provider: custom`, `base_url: http://localhost:11434/v1`, `default: qwen3:8b` (fast), `context_length: 65536`, `ollama_num_ctx: 65536` (Cortex needs ≥64K; Ollama defaults low).
- **Deep model `qwen3:14b` @ 64K FITS (~12 GB VRAM)** with KV-cache quant — user env `OLLAMA_FLASH_ATTENTION=1` + `OLLAMA_KV_CACHE_TYPE=q8_0` (set). Switch `default` to `qwen3:14b` for deep; per-request fast/deep selection is a later enhancement (the gateway serves one model at a time).

## Cortex install (native Windows, no Docker) — pinned 0.15.2
`iex (irm https://raw.githubusercontent.com/Cortex Labs/hermes-agent/main/scripts/install.ps1)` then
`& "%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe" -m pip install --upgrade hermes-agent==0.15.2`
(install.ps1's git-main is 0.15.1; pin to the PyPI release 0.15.2.) Installs under `%LOCALAPPDATA%\cortex`; `cortex gateway` runs natively on `127.0.0.1:8642`.
- **Persistence (no admin):** Startup launcher `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\ira-cortex-gateway.vbs` auto-starts the gateway hidden at logon (scheduled tasks need admin here). Start now: run that .vbs or `cortex gateway`.

## Reasoning skills vs the agentic gateway (Phase-6 note)
The gateway runs the FULL Cortex agent (files/shell/web tools). IRA's Option-A skills are reasoning-only (IRA runs the tools), so `skills/_common.run_skill` injects a no-tools directive. The model still sometimes over-reaches into a tool call (notably the security persona → tries to read `/var/log/auth.log`). Constraining/stripping the gateway toolset for reasoning skills is a **Phase-6** task.

## Voice (browser-native) — the default working path (verified 2026-06-13)
The LiveKit voice loop does NOT work on the native Shadow runtime (the `livekit` server
+ `ira-voice` agent only exist in docker-compose, so the frontend never gets a token →
"Voice unavailable — no token"). Voice now runs **browser-native**, gated by
`NEXT_PUBLIC_VOICE_TRANSPORT` (default `browser`; `livekit` = legacy, code untouched).
- **TTS:** on-device **Supertonic-3** (female `F1`). One synth core
  `voice/tts_supertonic.synthesize_wav` (44.1 kHz WAV) is shared by `POST /api/v1/voice/say`
  AND the LiveKit plugin. Engine via `voice/tts_factory.make_tts` (`IRA_VOICE_ENGINE=supertonic|kokoro`).
  The API pre-warms it at startup.
- **STT (sovereign):** local faster-whisper `voice/stt.transcribe_audio_bytes` behind
  `POST /api/v1/voice/transcribe` → `{text, is_owner}`; the SAME audio drives the ECAPA owner
  gate (`voice/gate.gate_from_audio`, fail-closed). DEV_MODE → `is_owner=true`.
  `NEXT_PUBLIC_VOICE_STT=webspeech` is the opt-in, NOT-private fast mode (badged in the UI).
- **Activation:** `NEXT_PUBLIC_VOICE_ACTIVATION=wakeword` ("hey ira") | `clap` (double-clap),
  in `frontend/components/VoiceConsole.tsx`. Barge-in stops playback.
- **Sovereignty seam — do NOT undo:** `voice/{tts,tts_supertonic,tts_factory,stt}.py` import
  livekit-agents **softly**, so the browser/HTTP path loads (and unit-tests) WITHOUT livekit;
  the LiveKit plugin classes bind the real base class only when livekit is present.
- **Engine:** the voice path pins the fast tier `qwen3:8b` (`is_voice` forces `use_deep=False`).
  `IRA_USE_CORTEX` toggles Ollama-direct vs Cortex for BOTH text and voice; both return real
  replies (direct-Ollama = lowest latency).
- **One command:** `start-ira.ps1` (Postgres→Redis→Ollama pull+warm→Cortex `cortex -z`→Supertonic
  warm→API→frontend); `-InstallAutostart` drops a Startup-folder (logon) launcher and
  `-InstallService` registers an AtStartup S4U task that runs with no login (see v2 below).

## IRA v2 (Part-6 playbook) — sovereign coding, mobile, multilingual, strategy
Additive on top of the browser-voice work; v1 voice loop + LiveKit untouched. Local-first.
- **Sovereign coding agent** (`agents/coding_agent.py::run_coding_task`): voice/text coding asks
  route here. **Owner-gated, branch-only, never edits main, no push.** `CODER_BACKEND=local`
  (default) drives Aider + Ollama `qwen2.5-coder:14b` (fits 20 GB; **32B only on 24 GB+** — a
  one-line env bump, never default); `=claude` is an explicit, logged cloud egress.
  delete/force-push/deploy → `needs-confirmation` (mirrors the gated self-modification rule).
- **Mobile PWA + Tailscale** (`frontend/public/sw.js`, `PWARegister.tsx`, `TAILSCALE_SETUP.md`):
  installable, large hold-to-talk button for phones. Phone access via **`tailscale serve` HTTPS**
  — `getUserMedia` needs a secure context, so the mic fails over plain http. `IRA_TS_HOST` +
  `NEXT_PUBLIC_API_BASE` set CORS/origin; `NEXT_PUBLIC_PWA=false` disables the SW. **No public port.**
- **Multilingual** (`voice/tts_indic.py` via `tts_factory.synthesize_say`): native Indic TTS
  (default IndicParler) for **ta/te/kn/ml**; **Hindi + Supertonic's other 30 languages stay on
  Supertonic**; **fail-soft to Supertonic `na`** if the Indic model is absent. STT: `WHISPER_MODEL`
  (default `distil-large-v3`; `large-v3` for Indic), tuned VAD (`WHISPER_VAD_*`), language auto-detect.
- **Strategy mode** (`agents/strategy_mode.py`, `is_strategy_request`/`run_strategy`): bounded,
  ranked, honest deliberation for explicit strategic asks; **off** the low-latency voice fast path.
  `STRATEGY_*` knobs (branches, depth ≤2, self-consistency, deep synthesis) in `config.py`.
- **Strategy calibration** (`agents/strategy_calibration.py`, `postgres/010_*`): persists each run's
  raw estimates; `POST /api/v1/strategy/outcome` records the real result; future runs apply a stored
  per-domain offset (shrunk for sparse data) toward the owner's track record — surfaced as
  "calibrated on N decisions". **Honest:** calibration vs the owner's OWN outcomes — NOT retraining,
  NOT ground-truth simulation. `strategy_calibration_enabled` (default on); fail-soft without a DB.
- **Unattended boot:** `start-ira.ps1 -InstallService` (AtStartup S4U, no login) for 24/7;
  `-InstallAutostart` is the logon-level launcher. Local only.
- **Out of scope (separate later playbook):** renting a GPU server / production deployment.

## Bridge shape (Phase 2 reference — HTTP client, not an import)
```python
from openai import OpenAI          # IRA already depends on openai==1.54.4 — no new dep
client = OpenAI(base_url=os.environ["IRA_CORTEX_URL"],   # http://127.0.0.1:8642/v1
                api_key=os.environ["IRA_CORTEX_KEY"])     # = Cortex API_SERVER_KEY
r = client.chat.completions.create(model="hermes-agent",
                                   messages=[{"role": "user", "content": prompt}])
text = r.choices[0].message.content
```
(Per-tenant memory later: pass an `X-Cortex-Session-Key` header — the Phase 5 isolation hook.)

## Ground truth about THIS repo (verified against the code, 2026-06-15)
- **Git root** = repo top (`private-Jarvis-main`). Open the AI coding assistant HERE; paths are relative to it. App code under **`supracloud-jarvis/ira/`**.
- **`requirements.txt` is at `supracloud-jarvis/ira/requirements.txt`** — none at the `supracloud-jarvis/` root. `.github/` lives at the git root (CI `working-directory: supracloud-jarvis/ira`; Dependabot `directory: /supracloud-jarvis/ira`).
- **Agents** (LangGraph today) at `supracloud-jarvis/ira/agents/`: `security.py, tutor.py, career.py, researcher.py, creator.py, website.py, conversational.py, digital.py, executor.py, expert_mode.py`, plus **`engineer_agent.py`, `architect_agent.py`** (the `_agent` suffix is on those two ONLY). `supervisor.py, graph.py, state.py` = the LangGraph router we RETIRE at the end.
- **Overlay home**: add `ira/cortex_bridge.py`, `ira/skills/`, `ira/subagents/` alongside existing code. Leave `ira/voice/`, `ira/config/`, `ira/memory/`, `ira/tests/` in place.

## Security ground truth (verified in code — wording matters)
- **Biometric gate** (`ira/voice/biometrics.py`): **fails CLOSED.** `is_owner_authenticated()` returns `False` on empty/sub-1s audio, no enrolled profile, model failure, or similarity < 0.75 (audit-logged). The function is half the story — the **router-level** "block non-owner on restricted domains" is the real Phase 4 check. **Do NOT rewrite the gate.**
- **Self-modification / "auto-deploy"** (`ira/utils/auto_implement.py`): **NO remote push** ("remote sync intentionally absent" — verified). A **human-gated local** pipeline exists: `git apply` → `git commit` → `docker compose restart`, triggered ONLY by an explicit `architect apply` (`is_apply_trigger`, `chat.py:311`, behind `pending_apply`). Accurate wording: **"gated local commit/restart, no remote push"** — NOT "no deploy path." Keep it gated; add a regression test.

## Workflow
Run `MERGE_PLAN.md` Part 6 prompts **one at a time, in order**. After each: **full report** (files changed + each acceptance-criterion result) → **commit to `merge/cortex-overlay`** (a remote push needs the owner's explicit go-ahead) → **STOP** for review. Never run two prompts back to back. When in doubt, ASK — never guess at scope. (Dev-backup commits to your own review branch are distinct from the IRA agent's runtime self-modification, which never pushes — Guardrail 5.)
