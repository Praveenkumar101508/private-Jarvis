# CLAUDE.md — read this first

This repo merges **Hermes** (the agent engine, pinned `hermes-agent==0.15.2`) with
**IRA** (the SupraCloud product on top). Full plan: **`MERGE_PLAN.md`**.
This file is **ground truth** — where it conflicts with `MERGE_PLAN.md`, this file wins.

## Non-negotiable rules
1. Hermes is a PINNED, VENDORED dependency. **NEVER edit Hermes core** or anything in `supracloud-jarvis/hermes-vendor/`. Extend ONLY via skills, subagents, MCP, and config.
2. **ALL IRA->Hermes calls go through `supracloud-jarvis/ira/hermes_bridge.py` only.** Nothing else imports Hermes.
3. Pin is **`hermes-agent==0.15.2`**. Never float. Upgrade only via a CI-tested bump.
4. Secrets live in **env**, never in the repo.
5. **Postgres = business data only.** Memory/recall belongs to Hermes.

## Ground truth about THIS repo (verified against the code, 2026-06-03)
- **Git root** = the repo top (`private-Jarvis` / `private-Jarvis-main`). Claude Code opens HERE; all paths below are relative to it. (If you open inside `supracloud-jarvis/` instead, drop that prefix everywhere.)
- App code lives under **`supracloud-jarvis/ira/`**.
- **`requirements.txt` is at `supracloud-jarvis/ira/requirements.txt`** — there is NO requirements file at the `supracloud-jarvis/` root. (Also present: `ira/requirements-test.txt`, `ira/voice/requirements.txt`.)
- **`.github/` lives at the git root** (beside `supracloud-jarvis/`). CI uses `working-directory: supracloud-jarvis/ira`; Dependabot uses `directory: /supracloud-jarvis/ira`.
- **Agents** (LangGraph today) at `supracloud-jarvis/ira/agents/`:
  `security.py, tutor.py, career.py, researcher.py, creator.py, website.py, conversational.py, digital.py, executor.py, expert_mode.py`
  and **`engineer_agent.py`, `architect_agent.py`** (the `_agent` suffix is on those two ONLY).
  `supervisor.py, graph.py, state.py` = the LangGraph router we RETIRE at the end.
- **Overlay home** = alongside the existing code: add `supracloud-jarvis/ira/hermes_bridge.py`, `supracloud-jarvis/ira/skills/`, `supracloud-jarvis/ira/subagents/`. Leave existing `ira/voice/`, `ira/config/`, `ira/memory/`, `ira/tests/` in place.

## Security ground truth (verified in code — get the wording exactly right)
- **Biometric gate** (`ira/voice/biometrics.py`): **fails CLOSED.** `is_owner_authenticated()` returns `False` on empty/sub-1s audio, no enrolled profile, model failure, or similarity < 0.75 (audit-logged). The function is only half the story — the **router-level** "block non-owner on restricted domains" is the real Phase 4 check. **Do NOT rewrite the gate.**
- **Self-modification / "auto-deploy"** (`ira/utils/auto_implement.py`): **NO remote push** — the file states "remote sync intentionally absent; IRA never pushes to remote automatically" (verified true). **BUT** a LOCAL pipeline exists: `git apply --check` -> `git apply` -> `git commit` (author from `OWNER_NAME`) -> `docker compose restart <services>`. It is **human-gated**: runs ONLY via an explicit `architect apply` command (`is_apply_trigger`, `chat.py:311`), after the diff is streamed for review and parked behind a `pending_apply` flag. Accurate wording: **"gated local commit/restart, no remote push"** — NOT "no deploy path." Keep it gated; never auto-trigger; add a regression test that (a) no `git push` exists and (b) apply requires the explicit trigger.

## Real Hermes library API (verified against `run_agent.py`)
    from run_agent import AIAgent
    agent = AIAgent(base_url="http://localhost:8001/v1", model="qwen3-8b", quiet_mode=True)
    result = agent.run_conversation("...")   # returns a DICT; result["final_response"] is the text

- **`quiet_mode=True` is required** when embedding as a library (else CLI spinners print to stdout).
- **`run_conversation()` returns a DICT** (`result["final_response"]` = reply text, `result["messages"]` = history) per the Hermes docs. Extract `["final_response"]` and coerce to str — or use `agent.chat(prompt)`, which returns the text directly. `ira/hermes_bridge.py` does this defensively (also handles a non-dict return).

## Workflow
Run the prompts in `MERGE_PLAN.md` Part 6 **one at a time, in order**. After each: produce a **full report** (files changed + each acceptance-criterion result), **commit and push to the `merge/hermes-overlay` backup branch**, then **STOP** for review before the next. Never run two prompts back to back. When in doubt, ask — never guess at scope. (This dev-backup push to your own review branch is distinct from the IRA agent's runtime self-modification, which never pushes — Guardrail 5.)
