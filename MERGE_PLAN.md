# MERGE_PLAN.md — SupraCloud IRA × Cortex

**The single source of truth for merging Cortex (the engine) and IRA (the product) into one system.**
Owner: Praveen Kumar Kamineti · Approach: **overlay, never hard-fork** · Engine: `hermes-agent==0.15.2`, run **out-of-process**

> Canonical plan, verified against the live repo and the actual machine (Shadow PC). `AGENTS.md` (repo root) is read-first ground truth; if anything here drifts from it, `AGENTS.md` wins.

---

## 0. How to use this

- Written for **you and the AI coding assistant**. Keep this at the repo root next to `AGENTS.md`.
- **Part 6** has copy-paste prompts. Run them **one at a time, in order**. After each, the AI coding assistant **stops and reports**; you verify the gate before the next.
- **Golden rule (everywhere):** Cortex is a pinned dependency you never edit; you extend only through **skills, subagents, MCP, and config**, and **all IRA→Cortex calls go through one bridge file**. Cortex runs **out-of-process** (its own native install) behind an OpenAI-compatible gateway; the bridge is an HTTP client. This is what keeps upgrades ~1 hour/month, keeps you sovereign, and lets you swap the engine in one file.
- **Path convention:** the AI coding assistant opens at the **git root** (`private-Jarvis-main`). Every path below is relative to that root. App code lives under `supracloud-jarvis/ira/`.

---

## 1. The two repositories

| | Cortex — **the brain** | IRA — **the body + moat** |
|---|---|---|
| Repo | `https://github.com/Cortex Labs/hermes-agent` | `https://github.com/Praveenkumar101508/private-Jarvis` |
| Branch | `main` | `claude/setup-private-session-1gF9a` (merge work on `merge/cortex-overlay`) |
| Package | **`hermes-agent==0.15.2`** — real, MIT, on PyPI. Installed in its OWN native env, **never in IRA's venv**. | private (your IP) |
| License | MIT (every released version is yours forever) | private |
| Role | Agent runtime: learning loop, memory, skills, subagents, model adapters, **gateway** | Vertical product: voice, biometric gate, SupraCloud business logic, brand |

**How IRA reaches Cortex (verified):** Cortex runs `cortex gateway` → an **OpenAI-compatible HTTP server on `127.0.0.1:8642`** (gated by `API_SERVER_ENABLED=true` + `API_SERVER_KEY`). IRA's bridge is an OpenAI-compatible **HTTP client** using IRA's *existing* `openai`/`httpx` — **no new dependency, no `requirements.txt` change.** The openai 1.x-vs-2.x conflict never arises because it's a wire protocol, not a shared import.

---

## 2. Decision record — your doubts, our recommendations, the outcomes

| # | Your doubt | Recommendation | Decision (locked) |
|---|---|---|---|
| 1 | "Why use Cortex's brain — we can see the code, why not build our own?" | The agent **runtime is a commodity** (MIT, converging, improved daily by a lab). Seeing code ≠ maintaining a moving 1M-line target. Your moat is the **vertical**. | **Use Cortex as the brain; build IRA's moat on top.** A lean auditable core is justified only later, if a bank's security team demands it — not day one. |
| 2 | "If Cortex commits daily, I can't read all those changes." | **Don't read commits.** Pin it, watch *releases* not commits, keep your code in extension points, let **Dependabot + CI** do the watching, isolate behind a **one-file bridge**. | **~1 hour/month, zero commits read.** The overlay rule makes this possible. |
| 3 | "If Cortex goes private, is IRA dead?" | **MIT is irrevocable** for released versions; you keep `0.15.2` forever. Popular projects get **forked** (Valkey, OpenTofu, OpenSearch). The **bridge swaps the engine** in one file. | **A license change can't take IRA down.** Vendor a frozen copy + thin bridge = bulletproof. "Build your own brain" is the **exit hatch**, not the plan. |

---

## 3. Verified ground truth (checked against code + the actual machine, 2026-06-03)

**Get the wording exactly right — later phases depend on it.**

- **Repo layout:** app code at `supracloud-jarvis/ira/`. **`requirements.txt` is at `supracloud-jarvis/ira/requirements.txt`** — none at the `supracloud-jarvis/` root. `.github/` lives at the **git root**.
- **Agent filenames:** `engineer_agent.py` and `architect_agent.py` carry the `_agent` suffix; the other 10 are clean. `supervisor.py / graph.py / state.py` are the LangGraph router we retire.
- **Dependency conflict → out-of-process (the pivot):** `hermes-agent==0.15.2` hard-pins `openai==2.24.0`, `pydantic==2.13.4`, `croniter==6.0.0`, `httpx==0.28.1`, `requests==2.33.0`, `tenacity==9.1.4` — all clash with IRA's pins (and IRA's `langchain-openai` needs `openai 1.x`). `pip install` is **proven ResolutionImpossible**. So Cortex is **NOT** installed in IRA's venv; it runs out-of-process and the bridge talks to its gateway over HTTP. The in-process `from run_agent import AIAgent` idea is **abandoned**.
- **Machine = the Shadow PC** (`SHADOW-CR4M2J8D`, RTX A4500 20 GB). Docker daemon **not running**; WSL is **v1** (no CUDA); **vLLM can't run natively on Windows**. **Ollama 0.24.0 is installed and running on `:11434`** (OpenAI-compatible). → **Model backend = Ollama, not vLLM. No Docker, no WSL.** (Only `gemma2` pulled so far; qwen3 must be pulled in Phase 1.)
- **Biometric gate** (`ira/voice/biometrics.py`): **fails CLOSED.** `is_owner_authenticated()` returns `False` on empty/sub-1s audio, no profile, model failure, or similarity < 0.75 (audit-logged). The real remaining work is **router-level** enforcement (block non-owner on restricted domains). **Do not rewrite the gate — verify it.**
- **Self-modification / "auto-deploy"** (`ira/utils/auto_implement.py`): **no remote push** ("remote sync intentionally absent" — verified). A **human-gated local** pipeline exists (`git apply` → `git commit` → `docker compose restart`), triggered ONLY by an explicit `architect apply` (`is_apply_trigger`, `chat.py:311`, behind `pending_apply`). Wording: **"gated local commit/restart, no remote push."** Keep it gated; add a regression test.

---

## 4. Target architecture & repo layout

**Cortex = brain (out-of-process), IRA = body + moat.**
- **Stays pure IRA:** Next.js frontend, LiveKit voice, **ECAPA biometric owner-gate**, SupraCloud vertical (investor outreach, client→agent generation, multi-tenant isolation), brand.
- **Becomes Cortex:** the 12 agents → **skills + subagents**; 5-agent deliberation → Cortex **subagent spawning**; memory → Cortex (Postgres keeps **business data only**); self-improvement → Cortex's loop (keep the local apply pipeline gated).
- **Retired:** the LangGraph `supervisor.py / graph.py / state.py` router — Cortex's classifier replaces it.

```
USER (browser / phone / voice)
        │
  IRA SHELL (pure IRA): Next.js UI · LiveKit voice · ECAPA owner-gate (the moat)
        │  (only entry point)
  supracloud-jarvis/ira/cortex_bridge.py   ← the ONLY thing in IRA that talks to Cortex
        │  OpenAI API over HTTP (IRA's existing openai/httpx client)
  CORTEX GATEWAY  127.0.0.1:8642  (native Windows, own install under %LOCALAPPDATA%\cortex, key-gated)
  learning loop · curated memory · skills · subagents · model adapters
        │  OpenAI API
  OLLAMA  127.0.0.1:11434  (native Windows, RTX A4500)   →  qwen3:8b (fast) · qwen3:14b (deep)
```

Repo tree (what lives in git; Cortex itself installs OUT of the tree, under `%LOCALAPPDATA%\cortex`):
```
private-Jarvis-main/                    # GIT ROOT (the AI coding assistant opens here)
├── AGENTS.md                           # read-first ground truth
├── MERGE_PLAN.md                       # this file
├── .github/                            # at the git root (GitHub reads it here)
│   ├── workflows/ci.yml                #   working-directory: supracloud-jarvis/ira
│   └── dependabot.yml                  #   directory: /supracloud-jarvis/ira
└── supracloud-jarvis/
    ├── cortex-vendor/                  # frozen copy of hermes-agent 0.15.2 for DR / certified build (DO NOT EDIT)
    ├── ira/
    │   ├── requirements.txt            # EXISTS — UNCHANGED (no hermes-agent here; it's out-of-process)
    │   ├── cortex_bridge.py            # the ONLY IRA file that talks to Cortex (HTTP client)
    │   ├── skills/                     # the 12 agents as Cortex skills (registered with the Cortex install)
    │   ├── subagents/                  # 5-agent deliberation definitions
    │   ├── agents/                     # EXISTS — LangGraph agents (port → skills, then retire router)
    │   ├── memory/                     # EXISTS — reranker/embeddings/store (Postgres = business data only)
    │   ├── voice/                      # EXISTS — LiveKit + STT/TTS + biometrics (front edge)
    │   ├── config/                     # EXISTS — Cortex/Ollama endpoint config + .env.example (no secrets)
    │   ├── api/  tasks/  utils/  worker/  tests/   # EXISTS
    └── frontend/                       # EXISTS — Next.js 14 UI
```

**Locked defaults:** Model backend = **Ollama** on `127.0.0.1:11434` (qwen3:8b fast / qwen3:14b deep), native, on the A4500 → sovereign, zero API cost. Cortex runs **native, out-of-process**, gateway on `127.0.0.1:8642`, key-gated. Voice + biometric gate sit in front. **Strip Cortex's `red-teaming/godmode` skills** before anything bank-facing.

**Pin AND vendor:** the Cortex install pins `hermes-agent==0.15.2`; keep a frozen copy in `supracloud-jarvis/cortex-vendor/` for disaster recovery and the certified bank build. Upgrade the pin on your schedule, never automatically in production.

---

## 5. Phased plan (each phase ends at a verify gate)

- **Phase 0 — Foundation & safety nets — ✅ DONE** (branch `merge/cortex-overlay`, commit `99b29fc`, not pushed): `AGENTS.md` + `MERGE_PLAN.md` at git root; `.github/` CI + Dependabot; `cortex-vendor/README`; empty `ira/cortex_bridge.py` stub; `ira/skills/` + `ira/subagents/` (.gitkeep); `ira/tests/test_smoke.py`. `hermes-agent` was deliberately **NOT** added to `ira/requirements.txt` (out-of-process). *Gate met:* smoke test passes; `git diff` clean; vendor README exists.
- **Phase 1 — Cortex gateway on the A4500 (Ollama backend):** pull qwen3 models into Ollama; install Cortex natively; point it at Ollama; run `cortex gateway` (key-gated, localhost). *Gate:* `GET 127.0.0.1:8642/v1/models` responds and one chat completion returns text from a local qwen3 model; cost £0.
- **Phase 2 — Bridge + first agent (Security):** implement `cortex_bridge.py` as an OpenAI-compatible **HTTP client** to the gateway; port `agents/security.py` → `skills/security/`; call it through the bridge. *Gate:* test passes via the bridge; `grep -rl "import cortex\|from run_agent\|import run_agent" supracloud-jarvis/ira/` returns **nothing** (IRA never imports Cortex); `git diff supracloud-jarvis/cortex-vendor/` empty.
- **Phase 3 — Port remaining agents (one at a time):** tutor, career, researcher, creator, website, conversational, digital, executor, plus `engineer_agent.py` and `architect_agent.py`. *Gate:* each answers via the bridge; vendor diff empty.
- **Phase 4 — Deliberation + voice/biometric front edge:** `expert_mode` → Cortex subagents; wire voice + the ECAPA gate in front. **Verify the gate stays fail-closed; implement router-level non-owner blocking on restricted domains.** *Gate:* owner passes, non-owner blocked on restricted domains, deliberation returns consensus.
- **Phase 5 — Frontend + business data:** Next.js → IRA API → bridge; Postgres holds business data only with tenant isolation (use the gateway's `X-Cortex-Session-Key` header to scope memory per tenant). *Gate:* full round trip + a test proving no cross-tenant reads.
- **Phase 6 — Harden, strip, freeze, rehearse:** strip `godmode`/red-team skills; confirm **no remote push** and keep the local apply pipeline **gated** (regression test); secrets to env; freeze the vendor copy; rehearse a `0.15.2 → 0.15.3` bump through CI. *Gate:* checklist green; simulated bump passes CI with zero changes to `ira/`.

---

## 6. The the AI coding assistant prompts

Run in order. Each is self-contained and repeats the rules so a fresh session can't drift. **Open the AI coding assistant at the git root.**

### Per-step protocol (applies to EVERY prompt below)
The closing `✅ … STOP` line means the AI coding assistant must, in order:
1. **Full report** — what it did, every file created/changed (with paths), each acceptance-criterion result (pass/fail), and anything it had to decide or that surprised it.
2. **Commit** the step to the **`merge/cortex-overlay`** branch with a clear message (e.g. `phase 2: bridge + security skill`). A **remote push needs the owner's explicit go-ahead** (auth + review) — commit locally otherwise.
3. **STOP** — wait for review before the next prompt. Never run two prompts back to back.

> This is the AI coding assistant backing up *development* work to your own review branch — deliberate and safe. It is **not** the IRA agent's runtime self-modification, which never pushes (Guardrail 5). Keep those two separate.

### Prompt 0 — Scaffold + safety nets  (✅ already executed; kept for the record)

```
## Context (carry forward — do not deviate)
Merging two projects into ONE system, IRA. Cortex = AGENT ENGINE, runs OUT-OF-PROCESS (own native install), pinned hermes-agent==0.15.2. IRA = PRODUCT on top (this repo).
GOLDEN RULE: never edit Cortex core; extend via skills/subagents/MCP/config. ALL IRA->Cortex calls go through ONE file: supracloud-jarvis/ira/cortex_bridge.py. Do NOT add hermes-agent to ira/requirements.txt (out-of-process; dep conflict).
You are at the GIT ROOT. App code is under supracloud-jarvis/ira/. .github/ goes at the git root.

<task>
Create the overlay skeleton + safety nets — only these:
- supracloud-jarvis/cortex-vendor/README.md ("Frozen copy of Cortex 0.15.2 — DO NOT EDIT. Regenerate only via a deliberate, audited version bump.")
- supracloud-jarvis/ira/cortex_bridge.py — empty stub, docstring: "the ONLY file allowed to talk to Cortex."
- supracloud-jarvis/ira/skills/.gitkeep and supracloud-jarvis/ira/subagents/.gitkeep
- supracloud-jarvis/ira/tests/test_smoke.py — one trivial passing test.
- ./.github/workflows/ci.yml — push/PR, working-directory: supracloud-jarvis/ira, install requirements.txt, run pytest.
- ./.github/dependabot.yml — pip, directory: /supracloud-jarvis/ira, watch ONLY hermes-agent (so you still get release PRs even though it's out-of-process).
- ./AGENTS.md — read-first ground truth.
Do NOT modify ira/requirements.txt (hermes-agent is NOT an IRA dependency).
</task>

<acceptance_criteria>
- `cd supracloud-jarvis/ira && pytest -q` passes the smoke test.
- `git diff` shows only the new files (requirements.txt UNCHANGED).
</acceptance_criteria>

After completing, output: ✅ Phase 0 done — list every file created, then STOP.
```

### Prompt 1 — Cortex gateway on Ollama (native Windows, no Docker)

```
## Context (carry forward)
Same system, same GOLDEN RULE. Cortex runs OUT-OF-PROCESS, native Windows, against a local Ollama backend. NO Docker, NO vLLM (this box: Shadow PC, RTX A4500 20GB; Docker daemon down; WSL v1; vLLM can't run native on Windows). Target: zero external API cost.

<task>
1. Ollama (already installed/running on :11434): `ollama pull qwen3:8b` and `ollama pull qwen3:14b`; confirm `GET http://localhost:11434/v1/models` lists them.
2. Install Cortex natively (NOT in IRA's venv): `iex (irm https://raw.githubusercontent.com/Cortex Labs/hermes-agent/main/scripts/install.ps1)` (installs under %LOCALAPPDATA%\cortex, isolated).
3. Configure Cortex (its own config — do NOT edit its source): provider: custom, base_url: http://localhost:11434/v1, default: qwen3:14b (qwen3:8b for fast), set context_length explicitly.
4. Start the gateway: env API_SERVER_ENABLED=true, API_SERVER_KEY=<32+ hex from env>, bound 127.0.0.1:8642 → `cortex gateway`.
5. Verify: `GET 127.0.0.1:8642/v1/models` (with key) + ONE chat completion through the gateway on a local model.
</task>

<constraints>
- Cortex config ONLY; do NOT edit cortex-vendor/ or Cortex core; Cortex is NOT installed into IRA's venv.
- Gateway stays on 127.0.0.1; API_SERVER_KEY in env, never committed.
- No paid external API — if anything defaults to cloud, STOP and tell me.
- Record chosen ports/models/key-var name in supracloud-jarvis/ira/config/ (placeholders + var names only, no secrets).
</constraints>

<acceptance_criteria>
- `GET 127.0.0.1:8642/v1/models` responds; one chat completion returns text from a local qwen3 model via Ollama. Cost £0.
- `git diff supracloud-jarvis/cortex-vendor/` is EMPTY.
</acceptance_criteria>

After completing, output: ✅ Phase 1 done — paste the gateway health + chat-completion output, then STOP for review.
```

### Prompt 2 — Bridge (HTTP client) + Security agent

```
## Context (carry forward)
Same system. GOLDEN RULE: supracloud-jarvis/ira/cortex_bridge.py is the ONLY IRA file that talks to Cortex — an HTTP client to the gateway (127.0.0.1:8642), NOT a Python import.
Verified integration — use IRA's EXISTING openai client, NO new dependency:
    from openai import OpenAI
    client = OpenAI(base_url=os.environ["IRA_CORTEX_URL"], api_key=os.environ["IRA_CORTEX_KEY"])
    r = client.chat.completions.create(model="hermes-agent", messages=[{"role":"user","content":prompt}])
    text = r.choices[0].message.content

<task>
1. Implement supracloud-jarvis/ira/cortex_bridge.py: a small documented HTTP client wrapping ONLY what we use — ask(prompt)->str now, deliberate() stub for Phase 4. Read base_url/key/model from env (IRA_CORTEX_URL / IRA_CORTEX_KEY / IRA_CORTEX_MODEL). Do NOT import hermes-agent; do NOT add it to requirements.txt.
2. Port supracloud-jarvis/ira/agents/security.py into a Cortex skill at supracloud-jarvis/ira/skills/security/ (agentskills.io format: SKILL.md + scripts). Preserve behavior; invent nothing new. Document how the skill dir is registered with the Cortex install.
3. Add a test in supracloud-jarvis/ira/tests/ that runs the Security skill THROUGH the bridge (against the running gateway) and asserts expected output.
</task>

<constraints>
- The bridge is the ONLY IRA file that talks to Cortex. Do NOT edit cortex-vendor/ or Cortex core. Do NOT add hermes-agent to ira/requirements.txt.
- Keep the Security skill's scope identical to the old agent. If unclear, summarize and ASK before guessing.
- Only what is requested.
</constraints>

<acceptance_criteria>
- The test passes: Security skill runs via the bridge (HTTP→gateway) and returns expected output.
- `grep -rl "import cortex\|from run_agent\|import run_agent" supracloud-jarvis/ira/` returns NOTHING (the bridge imports `openai`, not Cortex).
- `git diff supracloud-jarvis/cortex-vendor/` is EMPTY.
</acceptance_criteria>

After completing, output: ✅ Phase 2 done — show the bridge interface and the passing test, then STOP for review.
```

### Prompt 3 — Port the remaining agents (run once per agent)

```
## Context (carry forward)
Same system, same GOLDEN RULE. The bridge works; Security is live. Port the NEXT agent only.
Logical name -> source file (note the two with a suffix):
  tutor->tutor.py, career->career.py, researcher->researcher.py, creator->creator.py,
  website->website.py, conversational->conversational.py, digital->digital.py, executor->executor.py,
  engineer->engineer_agent.py, architect->architect_agent.py
Skill FOLDERS use the clean logical name (e.g. supracloud-jarvis/ira/skills/engineer/).

<task>
Port the "<LOGICAL_NAME>" agent (source: supracloud-jarvis/ira/agents/<SOURCE_FILE>) into a Cortex skill at supracloud-jarvis/ira/skills/<LOGICAL_NAME>/, agentskills.io format. Preserve behavior exactly. Add a test that runs it through the bridge.
For "engineer" and "architect" specifically: the existing local apply pipeline (git apply -> commit -> docker restart) is HUMAN-GATED behind `architect apply`. Preserve that gate exactly. Do NOT add any auto-trigger and do NOT add any `git push` / remote sync.
</task>

<constraints>
- One agent only — the one I named. Do NOT batch.
- IRA must not import Cortex. Do NOT edit supracloud-jarvis/cortex-vendor/.
- Preserve scope. Only what is requested.
</constraints>

<acceptance_criteria>
- New test passes through the bridge.
- `git diff supracloud-jarvis/cortex-vendor/` is EMPTY.
- For engineer/architect: confirm the apply gate is intact and NO remote push / auto-trigger was added.
</acceptance_criteria>

After completing, output: ✅ <LOGICAL_NAME> ported — then STOP. I will name the next agent.
```

### Prompt 4 — Deliberation + voice/biometric front edge

```
## Context (carry forward)
Same system, same GOLDEN RULE. All single agents are skills. Now the deliberation and IRA's front edge (the moat).
VERIFIED: the biometric gate (supracloud-jarvis/ira/voice/biometrics.py) ALREADY fails closed — is_owner_authenticated() returns False on empty/sub-1s audio, no profile, model failure, or similarity < 0.75. Do NOT rewrite it. The real work is router-level enforcement.

<task>
1. Implement the 5-agent deliberation (old expert_mode) using Cortex native subagent spawning — define subagents in supracloud-jarvis/ira/subagents/; expose `deliberate(question)` on the bridge that spawns them (via the gateway) and returns a consensus answer.
2. Wire IRA's voice pipeline (LiveKit + Faster-Whisper STT + Kokoro TTS) + the ECAPA gate so: audio -> STT -> is_owner_authenticated() -> if owner, route to Cortex via the bridge -> TTS reply.
3. Implement ROUTER-LEVEL enforcement: a non-owner (gate returns False) is BLOCKED from restricted domains. The gate function is only half the story — enforce the block in routing.
</task>

<constraints>
- Voice + gate are IRA's own code; they call Cortex ONLY through cortex_bridge.py. Do NOT edit supracloud-jarvis/cortex-vendor/.
- The gate already fails closed — VERIFY that, do not rewrite it. Routing MUST also fail closed (deny on uncertainty).
- Only what is requested.
</constraints>

<acceptance_criteria>
- Owner voice request passes and gets a spoken reply via Cortex.
- A non-owner (or spoofed) sample is BLOCKED on restricted domains at the router.
- deliberate() spawns subagents and returns a consensus result.
- `git diff supracloud-jarvis/cortex-vendor/` is EMPTY.
</acceptance_criteria>

After completing, output: ✅ Phase 4 done — describe the router-level block and confirm the gate was verified (not rewritten), then STOP for review.
```

### Prompt 5 — Frontend + business data

```
## Context (carry forward)
Same system, same GOLDEN RULE. Engine + skills + voice + gate work. Connect the Next.js UI and the business-data store.
IMPORTANT: Cortex owns MEMORY/recall. Postgres holds BUSINESS DATA ONLY (investor records, client->agent specs, tenant isolation). Do NOT build a second memory system. Per-tenant memory scoping uses the gateway's `X-Cortex-Session-Key` header.

<task>
1. Point the existing supracloud-jarvis/frontend (Next.js 14) at IRA's API (which calls Cortex via the bridge). Reuse the UI; do NOT redesign.
2. Define the business-data schema in supracloud-jarvis/ira/ (investor, client->agent, tenant isolation) + the access layer skills use.
3. Per tenant, pass a distinct `X-Cortex-Session-Key` through the bridge so Cortex memory is isolated per tenant.
4. Add an end-to-end test: UI -> bridge -> Cortex skill -> business data persisted -> retrievable.
</task>

<constraints>
- Postgres = business data only. Memory stays in Cortex.
- IRA must not import Cortex; all calls via cortex_bridge.py. Do NOT edit supracloud-jarvis/cortex-vendor/.
- Tenant isolation MUST be enforced at the data layer (no cross-tenant reads) AND via per-tenant session keys. Only what is requested; no UI redesign.
</constraints>

<acceptance_criteria>
- Full round trip works; e2e test passes.
- A tenant cannot read another tenant's rows (add a test proving it).
- `git diff supracloud-jarvis/cortex-vendor/` is EMPTY.
</acceptance_criteria>

After completing, output: ✅ Phase 5 done — show the schema and the passing e2e + isolation tests, then STOP for review.
```

### Prompt 6 — Harden, strip, freeze, rehearse

```
## Context (carry forward)
Same system, same GOLDEN RULE. Merge is functionally complete. Final pass: safe, sovereign, upgrade-proof.
VERIFIED: there is NO remote push today; a human-gated local apply pipeline exists (git apply -> commit -> docker restart) behind `architect apply`. Keep it gated; do not remove it.

<task>
1. Strip Cortex's red-teaming/godmode (and any jailbreak) skills from the loaded skill set for the bank build. Document what was disabled.
2. Audit + fix: any hardcoded secrets (-> env, incl. API_SERVER_KEY), any stored-XSS / SSRF paths flagged previously. Confirm the gateway stays bound to 127.0.0.1.
3. Add a regression test that (a) NO `git push` / remote sync exists anywhere, and (b) the local apply pipeline runs ONLY via the explicit `architect apply` trigger (never auto).
4. Freeze supracloud-jarvis/cortex-vendor/ as the certified copy (record version + checksum).
5. REHEARSE one upgrade on a throwaway branch: bump the Cortex install to a hypothetical 0.15.3, run full CI, confirm ZERO changes needed under supracloud-jarvis/ira/, then revert.
</task>

<constraints>
- Do NOT weaken the biometric fail-closed behavior or the apply gate. Do NOT commit real secrets.
- The rehearsal MUST be on a throwaway branch and reverted — do not actually bump the pin yet. Only what is requested.
</constraints>

<acceptance_criteria>
- Checklist passes: no hardcoded secrets; godmode/red-team disabled; no remote push; apply pipeline gated; XSS/SSRF closed; gateway localhost-bound.
- A frozen, checksummed vendor copy of 0.15.2 exists.
- The simulated 0.15.3 bump passes CI with ZERO changes to supracloud-jarvis/ira/.
</acceptance_criteria>

After completing, output: ✅ Phase 6 done — paste the checklist results and the rehearsal CI summary, then STOP. Merge complete.
```

---

### Prompt 7 — Cutover (reversible 3-stop)

> Status: **7.1–7.3 ✅ done + merged to trunk (PR #15, `393d94e`)** · **7.4 written below — HELD until a clean production soak of `IRA_USE_CORTEX=true`** (precondition; do not run before then).
> The riskiest change earns the most checkpoints. Run **7.1 → 7.2 → 7.3 one at a time**, same protocol, on a NEW branch `feat/cutover` off trunk. 7.4 (flip the production default + retire the legacy router) is a SEPARATE later prompt — it rests on real soak results, not a guess. The old LangGraph router stays one toggle away until you're confident.

#### Prompt 7.1 — pre-cutover security fixes

```
## Context (carry forward — do not deviate)
IRA (FastAPI + LangGraph, openai 1.x) runs on top of Cortex via an out-of-process OpenAI-compatible gateway. Trunk (claude/setup-private-session-1gF9a) is at merge 3a69c10 (PR #14): the Cortex path EXISTS and passes CI, but PRODUCTION STILL ROUTES THROUGH THE LEGACY LangGraph agents. We are now doing the CUTOVER — the riskiest step — so everything is reversible and verified.
GOLDEN RULES: Cortex is a pinned dep, never edited; all IRA->Cortex calls go through ira/cortex_bridge.py only; biometric + router gates fail CLOSED; no remote git push, ever.
Work on a NEW branch `feat/cutover` off trunk. Per-step protocol: full report -> commit + push to feat/cutover -> STOP.
Step 7.1: two security fixes that MUST land before the flag is flipped.

<task>
1. Lock Ollama to localhost: set OLLAMA_HOST=127.0.0.1 in the env/launcher that starts Ollama, and document it in ira/config/cortex.env.example. (It currently listens on 0.0.0.0, exposing the raw model on the network — unacceptable for the bank build.)
2. Make the Cortex gateway reasoning-only: the gateway is fully agentic (file/shell/web tools), but IRA's skills only need REASONING (all tools/DB/owner-gate stay in IRA). Configure the gateway so the agent serving IRA has NO file/shell/web tools — via Cortex's tool/skill enablement config or a dedicated minimal profile (config level, not just the prompt directive in skills/_common.py). This closes the earlier security-skill over-reach (it tried to read /var/log/auth.log) at the source.
</task>

<constraints>
- Do NOT edit Cortex core / cortex-vendor/. Config/profile only.
- The reasoning-only profile MUST actually remove tool capability, not merely instruct against it — verify by probing.
- Do NOT touch live chat/voice routing in this step (that's 7.2). Only what is requested.
</constraints>

<acceptance_criteria>
- Ollama no longer answers on the machine's external IP; the gateway (via 127.0.0.1) still works.
- With the reasoning-only profile, a probe asking a skill to read a host file (e.g. /var/log/auth.log) is refused / has no tool to do it — show before/after.
- All existing overlay tests still pass.
</acceptance_criteria>

After completing: ✅ 7.1 done — show the Ollama bind proof + the gateway before/after probe, commit + push to feat/cutover, then STOP.
```

Implementation note (7.1 as built): Ollama bind via `setx OLLAMA_HOST 127.0.0.1` + restart (now 127.0.0.1 only; external REFUSED). Reasoning-only via `cortex tools disable --platform api_server file terminal code_execution web browser delegation computer_use` (the API server is platform `api_server`). Both reproduced by `supracloud-jarvis/scripts/harden-gateway.ps1`.

#### Prompt 7.2 — feature flag (default OFF, legacy untouched)

```
## Context (carry forward)
Same system, GOLDEN RULES, branch feat/cutover, per-step protocol. 7.1 is done and verified.
Live entry points (verified): Chat = ira/api/routes/chat.py (`from agents.graph import run_graph`; `await run_graph(...)` at ~line 133 and ~line 222 streaming; plus agents.supervisor.classify / is_restricted_domain; the multi-agent SSE route ~line 502). Voice = ira/voice/agent.py.
New path = ira/router.py enforce_owner_gate() + ira/skills/* via ira/cortex_bridge.py (+ ira/subagents for deliberation/architect).
Step 7.2: add a reversible feature flag. DEFAULT OFF — legacy behavior unchanged when off.

<task>
1. Add env flag `IRA_USE_CORTEX` (default `false`), read once at startup, following the existing env pattern; document in ira/config/cortex.env.example.
2. Branch on the flag at the existing call sites in chat.py (both the run_graph calls and the multi-agent SSE route) and voice/agent.py:
   - OFF -> current legacy path (run_graph / supervisor) EXACTLY as today.
   - ON  -> ira/router.py enforce_owner_gate() then ira/skills/* via the bridge (ira/subagents for deliberation/architect/expert paths).
3. Add a test asserting routing honors the flag (off -> legacy invoked; on -> bridge/skills path invoked), with the bridge mocked so no live gateway is needed.
</task>

<constraints>
- DEFAULT the flag OFF. When OFF, do NOT change one byte of legacy behavior.
- Do NOT delete or modify agents/graph.py, agents/supervisor.py, agents/state.py — they are the rollback path.
- All IRA->Cortex calls still go through cortex_bridge.py only; owner gate stays fail-closed on both paths. Only what is requested.
</constraints>

<acceptance_criteria>
- IRA_USE_CORTEX unset/false: full existing suite still passes; a manual chat still flows through run_graph (show it).
- IRA_USE_CORTEX=true (bridge mocked): chat + voice reach enforce_owner_gate() -> skills path; new routing test passes.
- git diff touches only chat.py, voice/agent.py, the config/env example, and the new test.
</acceptance_criteria>

After completing: ✅ 7.2 done — show flag-off suite passing + flag-on routing test, commit + push, then STOP.
```

#### Prompt 7.3 — live verification, flag ON (staging/local; production stays OFF)

```
## Context (carry forward)
Same system, GOLDEN RULES, branch feat/cutover, per-step protocol. 7.1 + 7.2 done; flag defaults OFF; production still on legacy.
Step 7.3: prove the new path works END TO END with the full stack up, BEFORE enabling it in production. This step does NOT change the production default and does NOT retire anything.

<task>
Bring up the full local stack: Ollama 127.0.0.1:11434 (qwen3:8b/14b); Cortex gateway 127.0.0.1:8642 (reasoning-only profile, API_SERVER_ENABLED=true, API_SERVER_KEY set); IRA with IRA_USE_CORTEX=true. Run these LIVE checks and capture each result:
1. Owner gate: a NON-owner targeting a restricted domain (security/business/executor/system/architect-apply) is BLOCKED; owner is allowed.
2. Two ordinary skills (e.g. tutor, researcher) return sensible answers via the bridge.
3. Voice round-trip: audio -> STT -> biometric gate -> (owner) -> bridge -> TTS.
4. Deliberation: subagents.deliberate returns a consensus.
5. Architect: produces a DIFF only — does NOT apply or push (apply only on explicit `architect apply`).
</task>

<constraints>
- Do NOT flip the production default to ON. Staging/local verification only; leave IRA_USE_CORTEX=false in committed config.
- Do NOT retire agents/graph.py / supervisor.py / state.py — separate later step after a production soak.
- If ANY check fails or is ambiguous, STOP and report it — do not paper over it. Only what is requested.
</constraints>

<acceptance_criteria>
- All five live checks pass, each with evidence (request + response/refusal).
- Committed config still has IRA_USE_CORTEX=false (production unchanged).
</acceptance_criteria>

After completing: ✅ 7.3 done — paste the five live-check results, open PR `feat/cutover -> trunk` (do NOT merge yet), then STOP. This is the go/no-go gate for enabling Cortex in production.
```

After 7.3 the sequence shifted (the cutover code merged to trunk DORMANT with the flag OFF, PR #15),
so "going live" is no longer a merge — it's flipping the env flag. **Soak:** (1) `IRA_USE_CORTEX=true`
in staging/local — exercise chat + voice + a restricted-domain block, watch for errors and especially
TIMEOUTS (deliberation/architect ran 60–151s headless; ensure the gateway, any reverse proxy, and the
frontend all allow those durations on the ON path); (2) then `true` in production under real traffic;
(3) anything wrong → set `false` (instant rollback — legacy runs on Ollama, verified, so it's real);
(4) only after a clean prod soak → run **Prompt 7.4**.

> **Dependency-map correction (changes 7.4):** the original "delete `supervisor.py`/`graph.py`/`state.py`"
> is WRONG — they are shared/load-bearing, not legacy-only. The Cortex path imports
> `classify`/`is_restricted_domain`/`make_initial_state`/`IRAState`; `main.py` inits the LangGraph
> checkpointer; the architect route + scheduler use `agents/architect_agent`; `chat.py` imports the
> `agents/*._SYSTEM` persona constants. So **7.4 only flips the default — it deletes nothing.** The one
> genuinely-removable piece is `run_graph` + the OFF branch, and that IS the env-flag rollback — keep it.

#### Prompt 7.4 — make Cortex the default (flip the flag; keep everything as rollback)

```
## Context (carry forward — do not deviate)
IRA runs on Cortex via an out-of-process OpenAI-compatible gateway. Trunk (claude/setup-private-session-1gF9a, 393d94e) has the cutover machinery; IRA_USE_CORTEX defaults OFF. 7.1–7.3 are merged (PR #15). This is 7.4 — making Cortex the default.
PRECONDITION (the human attests): IRA_USE_CORTEX=true has already SOAKED in PRODUCTION with no issues — chat, voice, restricted-domain block, deliberation/architect all healthy, and the long deliberation/architect calls did NOT hit any proxy/client/gateway timeout. If that soak hasn't happened, STOP and say so — do not run this.
GOLDEN RULES unchanged: Cortex pinned/never-edited; all IRA->Cortex via cortex_bridge.py; gates fail-closed; no remote push.
Branch feat/cutover-default off trunk. Per-step protocol: full report -> commit + push -> STOP.

CRITICAL — do NOT delete the legacy modules. A dependency map shows agents/supervisor.py, agents/graph.py, agents/state.py are NOT legacy-only: the Cortex path imports classify + is_restricted_domain + make_initial_state + IRAState from them; main.py initializes the LangGraph checkpointer (get_graph/init_checkpointer) at startup; agents/architect_agent is used by the architect route AND the scheduler; chat.py imports the agents/*._SYSTEM persona constants. Deleting any of these breaks the app. This step does NOT remove them.

<task>
1. In chat.py, change the flag default from "false" to "true" so Cortex is the default when IRA_USE_CORTEX is unset. KEEP the flag and the OFF branch (run_graph calls) fully intact — IRA_USE_CORTEX=false must still force the legacy path. The flag stays as the instant rollback.
2. Update ira/config/cortex.env.example: document that the default is now true and that =false is the rollback to legacy.
3. Update ira/tests/test_cutover_flag.py: the unset/default case now expects the Cortex (run_skill) path; KEEP an explicit assertion that IRA_USE_CORTEX=false still routes to run_graph; keep the existing on/gate/fallback tests.
</task>

<constraints>
- Do NOT delete or modify agents/supervisor.py, agents/graph.py, agents/state.py, agents/*_agent.py, the agents/*._SYSTEM constants, or main.py's checkpointer init — shared/startup infrastructure.
- KEEP the flag and the OFF/legacy branch — this preserves the env-flag rollback.
- All IRA->Cortex calls still go through cortex_bridge.py; gates stay fail-closed. Only what is requested.
</constraints>

<acceptance_criteria>
- IRA_USE_CORTEX unset -> Cortex path (new default); IRA_USE_CORTEX=false -> still run_graph (rollback intact). Both proven by the test.
- Full app-importing suite passes LOCALLY (not just CI). git diff scoped to chat.py + cortex.env.example + the test.
</acceptance_criteria>

After completing: ✅ 7.4 done — show the default flip + the "=false still hits run_graph" test, commit + push to feat/cutover-default, open the PR (do NOT merge until prod is confirmed healthy on the new default), then STOP.
```

> The original wholesale legacy-code deletion is dropped: the modules are shared, and the only removable
> bit is the rollback. A later code-hygiene pass (strip `run_graph` + the OFF branch + the flag, once
> rollback is truly never needed) can be its own dependency-checked prompt — no rush, little upside.

---

## 7. Guardrails — never break these

1. **NEVER edit anything under `supracloud-jarvis/cortex-vendor/` or any Cortex core file.** Cortex runs out-of-process in its own native install; extend only via skills, subagents, MCP, config.
2. **ALWAYS pin `hermes-agent==0.15.2`** for the Cortex install. Never float. Upgrade only via a CI-tested bump.
3. **ALL IRA→Cortex calls go through `supracloud-jarvis/ira/cortex_bridge.py` only** (HTTP client to the gateway). **Nothing in `ira/` imports Cortex; `hermes-agent` is NOT in `ira/requirements.txt`.**
4. **The biometric gate fails closed — verify, don't rewrite.** Router enforcement must also fail closed.
5. **No remote push, ever. Keep the local apply pipeline gated** behind the explicit `architect apply` trigger — never auto-trigger.
6. **Strip `godmode`/red-team skills** for any bank-facing build.
7. **Secrets in env, never in the repo** (incl. `API_SERVER_KEY`). **Keep the Cortex gateway bound to `127.0.0.1`.**
8. **Postgres = business data only.** Memory belongs to Cortex.
9. **Tenant isolation at the data layer** — no cross-tenant reads, with a test — plus per-tenant `X-Cortex-Session-Key` for memory scoping.
10. **Vendor a frozen, checksummed copy** for disaster recovery and the certified build.
11. **Model backend = Ollama on the A4500** (`:11434`), native, zero API cost. No Docker, no WSL, no vLLM on this machine.

---

## 8. Definition of done

- IRA runs on Cortex **locally** on the A4500 via the out-of-process gateway, with **Ollama** Qwen3 — zero external API cost.
- Biometric gate **verified** fail-closed; **router blocks non-owners** on restricted domains.
- All 12 agents respond as skills through the bridge; 5-agent deliberation works via subagents.
- Voice round-trips; Next.js UI works; business data persists with tenant isolation enforced (data layer + session keys).
- `grep -rl "import cortex\|from run_agent\|import run_agent" supracloud-jarvis/ira/` returns **nothing**; `git diff supracloud-jarvis/cortex-vendor/` is **empty**.
- CI green; frozen vendor copy exists; one upgrade rehearsed with zero changes to `ira/`.
- No remote push; apply pipeline gated; gateway localhost-bound; no godmode/red-team; no hardcoded secrets.

---

### Appendix — pocket answers
- **Why not our own brain?** Runtime is the commodity; your moat is the vertical. Build your own only if a bank demands a lean auditable core — and even then, after running Cortex long enough to know which 5% you need.
- **Daily commits?** Read none. Pin + watch-releases + Dependabot + CI + bridge = ~1 hr/month.
- **Cortex goes private?** MIT is irrevocable; you keep 0.15.2 forever; forks happen; the bridge swaps the engine in one file. Vendor the frozen copy and you're bulletproof.
- **Why out-of-process?** Cortex hard-pins openai 2.x etc., which conflict with IRA's openai 1.x stack. Running Cortex behind its OpenAI-compatible gateway turns a dependency clash into a clean wire-protocol boundary — more auditable than an in-process import, and the engine stays swappable in one file.
