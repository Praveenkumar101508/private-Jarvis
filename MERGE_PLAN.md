# MERGE_PLAN.md — SupraCloud IRA × Hermes

**The single source of truth for merging Hermes (the engine) and IRA (the product) into one system.**
Owner: Praveen Kumar Kamineti · Approach: **overlay, never hard-fork** · Engine pin: `hermes-agent==0.15.2`

> This is the canonical plan. All paths are verified against the live repo. `CLAUDE.md` (repo root) is read-first ground truth; if anything here ever drifts from it, `CLAUDE.md` wins.

---

## 0. How to use this

- Written for **you and Claude Code**. Keep this at the repo root next to `CLAUDE.md`.
- **Part 6** has copy-paste prompts. Run them **one at a time, in order**. After each, Claude Code **stops and reports**; you verify the gate before the next.
- **Golden rule (everywhere):** Hermes is a pinned, vendored dependency. You never edit Hermes core. You extend only through **skills, subagents, MCP, and config**, and all IRA→Hermes calls go through **one bridge file**. This is what makes upgrades ~1 hour/month, keeps you sovereign, and lets you swap the engine in one file.
- **Path convention:** Claude Code opens at the **git root** (`private-Jarvis` / `private-Jarvis-main`). Every path below is relative to that root. App code lives under `supracloud-jarvis/ira/`.

---

## 1. The two repositories

| | Hermes — **the brain** | IRA — **the body + moat** |
|---|---|---|
| Repo | `https://github.com/NousResearch/hermes-agent` | `https://github.com/Praveenkumar101508/private-Jarvis` |
| Branch | `main` | `claude/setup-private-session-1gF9a` |
| Package | **`hermes-agent==0.15.2`** — real, MIT, on PyPI; usable as a library | private (your IP) |
| License | MIT (every released version is yours forever) | private |
| Role | Agent runtime: learning loop, memory, skills, subagents, model adapters, gateway | Vertical product: voice, biometric gate, SupraCloud business logic, brand |

**Verified Hermes library API** (against `run_agent.py`):
```python
from run_agent import AIAgent
agent = AIAgent(base_url="http://localhost:8001/v1", model="qwen3-8b", quiet_mode=True)
result = agent.run_conversation("...")   # returns a DICT; result["final_response"] is the text
```
`quiet_mode=True` is **required** for library embedding. `run_conversation()` returns a **dict** (`result["final_response"]` = text, `result["messages"]` = history) per the Hermes docs; `chat()` returns the text directly. The bridge extracts `final_response` defensively.

---

## 2. Decision record — your doubts, our recommendations, the outcomes

| # | Your doubt | Recommendation | Decision (locked) |
|---|---|---|---|
| 1 | "Why use Hermes's brain — we can see the code, why not build our own?" | The agent **runtime is a commodity** (MIT, converging, improved daily by a lab). Seeing code ≠ maintaining a moving 1M-line target. Your moat is the **vertical**. | **Use Hermes as the brain; build IRA's moat on top.** A lean auditable core is justified only later, if a bank's security team demands it — not day one. |
| 2 | "If Hermes commits daily, I can't read all those changes." | **Don't read commits.** Pin it, watch *releases* not commits, keep your code in extension points, let **Dependabot + CI** do the watching, isolate behind a **one-file bridge**. | **~1 hour/month, zero commits read.** The overlay rule makes this possible. |
| 3 | "If Hermes goes private, is IRA dead?" | **MIT is irrevocable** for released versions; you keep `0.15.2` forever. Popular projects get **forked** (Valkey, OpenTofu, OpenSearch). The **bridge swaps the engine** in one file. | **A license change can't take IRA down.** Vendor a frozen copy + thin bridge = bulletproof. "Build your own brain" is the **exit hatch**, not the plan. |

---

## 3. Verified ground truth (checked against the actual code, 2026-06-03)

These correct the original audit assumptions. **Get the wording exactly right — Phases 4 and 6 depend on it.**

- **Repo layout:** app code at `supracloud-jarvis/ira/`. **`requirements.txt` is at `supracloud-jarvis/ira/requirements.txt`** — there is no requirements file at the `supracloud-jarvis/` root. `.github/` lives at the **git root** (beside `supracloud-jarvis/`).
- **Agent filenames:** `engineer_agent.py` and `architect_agent.py` carry the `_agent` suffix; the other 10 are clean. `supervisor.py / graph.py / state.py` are the LangGraph router we retire.
- **Biometric gate** (`ira/voice/biometrics.py`): **fails CLOSED.** `is_owner_authenticated()` returns `False` on empty/sub-1s audio, no profile, model failure, or similarity < 0.75 (audit-logged). The real remaining work is **router-level** enforcement (block non-owner on restricted domains). **Do not rewrite the gate — verify it.**
- **Self-modification / "auto-deploy"** (`ira/utils/auto_implement.py`): **no remote push** ("remote sync intentionally absent" — verified). **But** a **human-gated local** pipeline exists: `git apply --check` → `git apply` → `git commit` → `docker compose restart <services>`, triggered ONLY by an explicit `architect apply` command (`is_apply_trigger`, `chat.py:311`) after the diff is shown and parked behind `pending_apply`. Accurate wording: **"gated local commit/restart, no remote push."** Keep it gated; add a regression test.

---

## 4. Target architecture & repo layout

**Hermes = brain, IRA = body + moat.**
- **Stays pure IRA:** Next.js frontend, LiveKit voice, **ECAPA biometric owner-gate**, SupraCloud vertical (investor outreach, client→agent generation, multi-tenant isolation), brand.
- **Becomes Hermes:** the 12 agents → **skills + subagents**; 5-agent deliberation → Hermes **subagent spawning**; memory → Hermes (Postgres keeps **business data only**); self-improvement → Hermes's loop (keep the local apply pipeline gated).
- **Retired:** the LangGraph `supervisor.py / graph.py / state.py` router — Hermes's classifier replaces it.

```
private-Jarvis-main/                    # GIT ROOT (Claude Code opens here)
├── CLAUDE.md                           # NEW — read-first ground truth
├── MERGE_PLAN.md                       # NEW — this file
├── .github/                            # NEW — at the git root (GitHub reads it here)
│   ├── workflows/ci.yml                #   cd's into supracloud-jarvis/ira to test
│   └── dependabot.yml                  #   directory: /supracloud-jarvis/ira
└── supracloud-jarvis/
    ├── hermes-vendor/                  # NEW — frozen copy of Hermes 0.15.2 (DO NOT EDIT)
    ├── ira/
    │   ├── requirements.txt            # EXISTS — add the hermes-agent pin here
    │   ├── requirements-test.txt       # EXISTS
    │   ├── hermes_bridge.py            # NEW — the ONLY file importing Hermes
    │   ├── skills/                     # NEW — the 12 agents as Hermes skills
    │   ├── subagents/                  # NEW — 5-agent deliberation definitions
    │   ├── agents/                     # EXISTS — LangGraph agents (port -> skills, then retire router)
    │   ├── memory/                     # EXISTS — reranker/embeddings/store (Postgres = business data only)
    │   ├── voice/                      # EXISTS — LiveKit + STT/TTS + biometrics (front edge)
    │   ├── config/                     # EXISTS — vllm + .env.example live here
    │   ├── api/  tasks/  utils/  worker/  tests/   # EXISTS
    └── frontend/                       # EXISTS — Next.js 14 UI
```

**Locked defaults:** Hermes points at local **vLLM Qwen3** (8001 fast / 8002 deep) → sovereign, zero API cost. Voice + biometric gate sit in front. **Strip Hermes's `red-teaming/godmode` skills** before anything bank-facing.

**Pin AND vendor:** pin `hermes-agent==0.15.2` in `ira/requirements.txt`; keep a frozen copy in `supracloud-jarvis/hermes-vendor/` for disaster recovery and the certified bank build. Upgrade the pin on your schedule, never automatically in production.

---

## 5. Phased plan (each phase ends at a verify gate)

- **Phase 0 — Foundation & safety nets:** pin in `ira/requirements.txt`; `hermes-vendor/`; empty `ira/hermes_bridge.py`; `ira/skills/` + `ira/subagents/`; `.github/` (CI + Dependabot) at git root; root `CLAUDE.md`. *Gate:* `cd supracloud-jarvis/ira && pip install -r requirements.txt` works; CI runs; vendor copy exists.
- **Phase 1 — Hermes local on the A4500:** Hermes answers via local vLLM Qwen3, no external API. *Gate:* a CLI task completes on local models; cost £0.
- **Phase 2 — Bridge + first agent (Security):** implement `hermes_bridge.py`; port `agents/security.py` → `skills/security/`; call it through the bridge. *Gate:* test passes via the bridge; `grep -rl "import hermes\|from run_agent" supracloud-jarvis/ira/` lists only `hermes_bridge.py`; `git diff supracloud-jarvis/hermes-vendor/` empty.
- **Phase 3 — Port remaining agents (one at a time):** tutor, career, researcher, creator, website, conversational, digital, executor, plus `engineer_agent.py` and `architect_agent.py`. *Gate:* each answers via the bridge; vendor diff empty.
- **Phase 4 — Deliberation + voice/biometric front edge:** `expert_mode` → Hermes subagents; wire voice + the ECAPA gate in front. **Verify the gate stays fail-closed; implement router-level non-owner blocking on restricted domains.** *Gate:* owner passes, non-owner blocked on restricted domains, deliberation returns consensus.
- **Phase 5 — Frontend + business data:** Next.js → IRA API → bridge; Postgres holds business data only with tenant isolation. *Gate:* full round trip + a test proving no cross-tenant reads.
- **Phase 6 — Harden, strip, freeze, rehearse:** strip `godmode`/red-team skills; confirm **no remote push** and keep the local apply pipeline **gated** (regression test); secrets to env; freeze the vendor copy; rehearse a `0.15.2 → 0.15.3` bump through CI. *Gate:* checklist green; simulated bump passes CI with zero changes to `ira/`.

---

## 6. The Claude Code prompts

Run in order. Each is self-contained and repeats the rules so a fresh session can't drift. **Open Claude Code at the git root.**

### Per-step protocol (applies to EVERY prompt below)
The closing `✅ … STOP` line in each prompt means Claude Code must do these, in order:
1. **Full report** — what it did, every file created/changed (with paths), each acceptance-criterion result (pass/fail), and anything it had to decide or that surprised it. So you always have a clear record of what happened at each step.
2. **Commit + push** — commit the step with a clear message (e.g. `phase 2: bridge + security skill`) and push to a dedicated backup branch on your private repo, **`merge/hermes-overlay`**, so the work can never be lost.
3. **STOP** — wait for your review before the next prompt. Never run two prompts back to back.

> This is Claude Code backing up *development* work to **your own** repo on a review branch — deliberate and safe. It is **not** the IRA agent's runtime self-modification, which still never pushes (Guardrail 5). Keep those two separate.

### Prompt 0 — Scaffold + safety nets

```
## Context (carry forward — do not deviate)
Merging two projects into ONE system, IRA:
- Hermes = AGENT ENGINE. Real MIT pip package, pinned `hermes-agent==0.15.2`. Repo: https://github.com/NousResearch/hermes-agent
- IRA = PRODUCT on top. This repo (branch claude/setup-private-session-1gF9a).
GOLDEN RULE: Hermes is a PINNED, VENDORED dependency. NEVER edit Hermes core. Extend ONLY via skills, subagents, MCP, config. All IRA->Hermes calls go through ONE file: supracloud-jarvis/ira/hermes_bridge.py.
You are at the GIT ROOT. App code is under supracloud-jarvis/ira/. requirements.txt is at supracloud-jarvis/ira/requirements.txt (NONE at the supracloud-jarvis/ root). .github/ goes at the git root.

<task>
Create the overlay skeleton and upgrade-safety nets — only these, nothing more:
- Append `hermes-agent==0.15.2` to supracloud-jarvis/ira/requirements.txt (do NOT rewrite the file; keep all existing deps).
- supracloud-jarvis/hermes-vendor/README.md stating "Frozen copy of Hermes 0.15.2 — DO NOT EDIT. Regenerate only via a deliberate, audited version bump."
- supracloud-jarvis/ira/hermes_bridge.py — empty module, docstring: "the ONLY file allowed to import Hermes internals."
- supracloud-jarvis/ira/skills/.gitkeep and supracloud-jarvis/ira/subagents/.gitkeep
- supracloud-jarvis/ira/tests/test_smoke.py — one trivial passing test (the tests/ dir already exists).
- ./.github/workflows/ci.yml — runs on push/PR, `working-directory: supracloud-jarvis/ira`, installs requirements.txt, runs pytest.
- ./.github/dependabot.yml — pip ecosystem, `directory: /supracloud-jarvis/ira`, watches ONLY `hermes-agent`.
- ./CLAUDE.md — tells future sessions to read MERGE_PLAN.md first and never edit supracloud-jarvis/hermes-vendor/.
</task>

<constraints>
- Create ONLY the files listed. Do NOT scaffold agent logic. Do NOT recreate existing dirs (voice/, config/, memory/, agents/, api/, etc.).
- Do NOT delete or move existing files without listing them and asking first.
- No real secrets anywhere. When done, commit and push to the `merge/hermes-overlay` backup branch (see Per-step protocol). The only forbidden push is the IRA *agent's* runtime self-modification (Guardrail 5).
- Only make changes directly requested. No refactors, no extra features.
</constraints>

<acceptance_criteria>
- `cd supracloud-jarvis/ira && pip install -r requirements.txt` succeeds.
- `cd supracloud-jarvis/ira && pytest -q` passes the smoke test.
- `git diff` shows only the new files + the one appended requirements line.
</acceptance_criteria>

After completing, output: ✅ Phase 0 done — list every file created/changed, then STOP and wait for my review. Do not start Phase 1.
```

### Prompt 1 — Hermes local on vLLM Qwen3

```
## Context (carry forward)
Same system, same GOLDEN RULE (never edit Hermes core; config only). Hardware: NVIDIA RTX A4500 (20GB). Target: zero external API cost.

<task>
Get Hermes running locally against local vLLM Qwen3, via Hermes config only (NOT by editing its source):
1. Stand up two OpenAI-compatible vLLM endpoints: Qwen3-8B-AWQ (fast, ~7GB, :8001) and Qwen3-14B-AWQ (deep, ~12GB, :8002). Record them in supracloud-jarvis/ira/config/.
2. Configure Hermes to use these as its model provider via its documented custom-endpoint path.
3. Run one simple end-to-end task through the Hermes CLI on local models.
</task>

<constraints>
- Configure models ONLY through Hermes config/env. Do NOT edit anything under supracloud-jarvis/hermes-vendor/ or any Hermes core file.
- Verify both models fit in 20GB or document a fast<->deep swap. Do NOT call any paid external API — if something defaults to cloud, STOP and tell me.
- Only what is requested.
</constraints>

<acceptance_criteria>
- A simple Hermes task completes end-to-end using ONLY the local vLLM endpoints.
- `git diff supracloud-jarvis/hermes-vendor/` is EMPTY.
</acceptance_criteria>

After completing, output: ✅ Phase 1 done — paste the command you ran and its output, then STOP for review.
```

### Prompt 2 — Bridge + Security agent

```
## Context (carry forward)
Same system. GOLDEN RULE: supracloud-jarvis/ira/hermes_bridge.py is the ONLY module that imports Hermes — every other IRA file talks to Hermes through it (anti-corruption layer + engine-swap exit hatch).
Verified Hermes API: `from run_agent import AIAgent`; `AIAgent(base_url=..., model=..., quiet_mode=True)` (quiet_mode REQUIRED for embedding); `agent.run_conversation(prompt)` returns result["final_response"] (typed Any — coerce to str, do NOT assume a clean string or the full dict).

<task>
1. Implement supracloud-jarvis/ira/hermes_bridge.py: a small documented interface wrapping ONLY what we use — run a task and return a string. Use quiet_mode=True; coerce the run_conversation return to str.
2. Port supracloud-jarvis/ira/agents/security.py into a Hermes skill at supracloud-jarvis/ira/skills/security/ (agentskills.io format: SKILL.md + scripts). Preserve behavior; invent nothing new.
3. Add a test in supracloud-jarvis/ira/tests/ that runs the Security skill THROUGH the bridge and asserts expected output.
</task>

<constraints>
- Import Hermes internals ONLY in hermes_bridge.py. Do NOT edit supracloud-jarvis/hermes-vendor/.
- Keep the Security skill's scope identical to the old agent. If its logic is unclear, summarize and ASK before guessing.
- Only what is requested.
</constraints>

<acceptance_criteria>
- The test passes: Security skill runs via the bridge, returns expected output.
- `grep -rl "import hermes\|from run_agent" supracloud-jarvis/ira/` lists ONLY hermes_bridge.py.
- `git diff supracloud-jarvis/hermes-vendor/` is EMPTY.
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
Port the "<LOGICAL_NAME>" agent (source: supracloud-jarvis/ira/agents/<SOURCE_FILE>) into a Hermes skill at supracloud-jarvis/ira/skills/<LOGICAL_NAME>/, agentskills.io format. Preserve behavior exactly. Add a test that runs it through the bridge.
For "engineer" and "architect" specifically: the existing local apply pipeline (git apply -> commit -> docker restart) is HUMAN-GATED behind `architect apply`. Preserve that gate exactly. Do NOT add any auto-trigger and do NOT add any `git push` / remote sync.
</task>

<constraints>
- One agent only — the one I named. Do NOT batch.
- Import Hermes only in hermes_bridge.py. Do NOT edit supracloud-jarvis/hermes-vendor/.
- Preserve scope. Only what is requested.
</constraints>

<acceptance_criteria>
- New test passes through the bridge.
- `git diff supracloud-jarvis/hermes-vendor/` is EMPTY.
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
1. Implement the 5-agent deliberation (old expert_mode) using Hermes native subagent spawning — define subagents in supracloud-jarvis/ira/subagents/; expose `deliberate(question)` on the bridge that spawns them and returns a consensus answer.
2. Wire IRA's voice pipeline (LiveKit + Faster-Whisper STT + Kokoro TTS) + the ECAPA gate so: audio -> STT -> is_owner_authenticated() -> if owner, route to Hermes via the bridge -> TTS reply.
3. Implement ROUTER-LEVEL enforcement: a non-owner (gate returns False) is BLOCKED from restricted domains. The gate function is only half the story — enforce the block in routing.
</task>

<constraints>
- Voice + gate are IRA's own code; they call Hermes ONLY through hermes_bridge.py. Do NOT edit supracloud-jarvis/hermes-vendor/.
- The gate already fails closed — VERIFY that, do not rewrite it. Routing MUST also fail closed (deny on uncertainty).
- Only what is requested.
</constraints>

<acceptance_criteria>
- Owner voice request passes and gets a spoken reply via Hermes.
- A non-owner (or spoofed) sample is BLOCKED on restricted domains at the router.
- deliberate() spawns subagents and returns a consensus result.
- `git diff supracloud-jarvis/hermes-vendor/` is EMPTY.
</acceptance_criteria>

After completing, output: ✅ Phase 4 done — describe the router-level block and confirm the gate was verified (not rewritten), then STOP for review.
```

### Prompt 5 — Frontend + business data

```
## Context (carry forward)
Same system, same GOLDEN RULE. Engine + skills + voice + gate work. Connect the Next.js UI and the business-data store.
IMPORTANT: Hermes owns MEMORY/recall. Postgres holds BUSINESS DATA ONLY (investor records, client->agent specs, tenant isolation). Do NOT build a second memory system.

<task>
1. Point the existing supracloud-jarvis/frontend (Next.js 14) at IRA's API (which calls Hermes via the bridge). Reuse the UI; do NOT redesign.
2. Define the business-data schema in supracloud-jarvis/ira/ (investor, client->agent, tenant isolation) + the access layer skills use.
3. Add an end-to-end test: UI -> bridge -> Hermes skill -> business data persisted -> retrievable.
</task>

<constraints>
- Postgres = business data only. Memory stays in Hermes.
- Import Hermes only in hermes_bridge.py. Do NOT edit supracloud-jarvis/hermes-vendor/.
- Tenant isolation MUST be enforced at the data layer (no cross-tenant reads). Only what is requested; no UI redesign.
</constraints>

<acceptance_criteria>
- Full round trip works; e2e test passes.
- A tenant cannot read another tenant's rows (add a test proving it).
- `git diff supracloud-jarvis/hermes-vendor/` is EMPTY.
</acceptance_criteria>

After completing, output: ✅ Phase 5 done — show the schema and the passing e2e + isolation tests, then STOP for review.
```

### Prompt 6 — Harden, strip, freeze, rehearse

```
## Context (carry forward)
Same system, same GOLDEN RULE. Merge is functionally complete. Final pass: safe, sovereign, upgrade-proof.
VERIFIED: there is NO remote push today; a human-gated local apply pipeline exists (git apply -> commit -> docker restart) behind `architect apply`. Keep it gated; do not remove it.

<task>
1. Strip Hermes's red-teaming/godmode (and any jailbreak) skills from the loaded skill set for the bank build. Document what was disabled.
2. Audit + fix: any hardcoded secrets (-> env), any stored-XSS / SSRF paths flagged previously.
3. Add a regression test that (a) NO `git push` / remote sync exists anywhere, and (b) the local apply pipeline runs ONLY via the explicit `architect apply` trigger (never auto).
4. Freeze supracloud-jarvis/hermes-vendor/ as the certified copy (record version + checksum).
5. REHEARSE one upgrade on a throwaway branch: bump to a hypothetical 0.15.3, run full CI, confirm ZERO changes needed under supracloud-jarvis/ira/, then revert.
</task>

<constraints>
- Do NOT weaken the biometric fail-closed behavior or the apply gate. Do NOT commit real secrets.
- The rehearsal MUST be on a throwaway branch and reverted — do not actually bump the pin yet. Only what is requested.
</constraints>

<acceptance_criteria>
- Checklist passes: no hardcoded secrets; godmode/red-team disabled; no remote push; apply pipeline gated; XSS/SSRF closed.
- A frozen, checksummed vendor copy of 0.15.2 exists.
- The simulated 0.15.3 bump passes CI with ZERO changes to supracloud-jarvis/ira/.
</acceptance_criteria>

After completing, output: ✅ Phase 6 done — paste the checklist results and the rehearsal CI summary, then STOP. Merge complete.
```

---

## 7. Guardrails — never break these

1. **NEVER edit anything under `supracloud-jarvis/hermes-vendor/` or any Hermes core file.** Extend only via skills, subagents, MCP, config.
2. **ALWAYS pin `hermes-agent==0.15.2`.** Never float. Upgrade only via a CI-tested bump.
3. **ALL IRA→Hermes calls go through `supracloud-jarvis/ira/hermes_bridge.py` only.**
4. **The biometric gate fails closed — verify, don't rewrite.** Router enforcement must also fail closed.
5. **No remote push, ever. Keep the local apply pipeline gated** behind the explicit `architect apply` trigger — never auto-trigger.
6. **Strip `godmode`/red-team skills** for any bank-facing build.
7. **Secrets in env, never in the repo.**
8. **Postgres = business data only.** Memory belongs to Hermes.
9. **Tenant isolation at the data layer** — no cross-tenant reads, with a test.
10. **Vendor a frozen, checksummed copy** for disaster recovery and the certified build.

---

## 8. Definition of done

- IRA boots on Hermes **locally** on the A4500 with vLLM Qwen3 — zero external API cost.
- Biometric gate **verified** fail-closed; **router blocks non-owners** on restricted domains.
- All 12 agents respond as skills through the bridge; 5-agent deliberation works via subagents.
- Voice round-trips; Next.js UI works; business data persists with tenant isolation enforced.
- `grep -rl "import hermes\|from run_agent" supracloud-jarvis/ira/` returns **only** `hermes_bridge.py`; `git diff supracloud-jarvis/hermes-vendor/` is **empty**.
- CI green; frozen vendor copy exists; one upgrade rehearsed with zero changes to `ira/`.
- No remote push; apply pipeline gated; no godmode/red-team; no hardcoded secrets.

---

### Appendix — pocket answers
- **Why not our own brain?** Runtime is the commodity; your moat is the vertical. Build your own only if a bank demands a lean auditable core — and even then, after running Hermes long enough to know which 5% you need.
- **Daily commits?** Read none. Pin + watch-releases + Dependabot + CI + bridge = ~1 hr/month.
- **Hermes goes private?** MIT is irrevocable; you keep 0.15.2 forever; forks happen; the bridge swaps the engine in one file. Vendor the frozen copy and you're bulletproof.
