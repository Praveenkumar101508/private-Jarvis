# Cortex Dependency Finding — V1·Phase 1

**Question:** with `IRA_USE_CORTEX=false`, what does IRA still do natively, what
breaks or degrades, and where is the boundary between IRA's own code and what the
Cortex bridge ("Hermes" in the brief) was providing?

**Method:** static path-tracing of the two engine paths plus a live diagnostic
exercising the pure-Python paths with the flag off. A live Ollama/Postgres/Redis
stack is not present in this container, so the model-call leaf and DB leaf are
traced, not invoked; everything above them is exercised directly. The strongest
single piece of evidence is that the **full suite (715 passed, 11 skipped, 0
failed) runs at the default `IRA_USE_CORTEX=false`** — native IRA is what the
tests already cover.

## The boundary, in one line

> **Native IRA does everything; Cortex was providing an *alternative reasoning
> engine only*.** With the flag off (the default), chat, memory, classify/route,
> the owner-gate, and tool execution all run on IRA's own LangGraph + `utils.llm`
> path. Cortex (`cortex -z`, the hermes-agent CLI) only swaps *who generates the
> reasoning text* — it adds no tools, no memory, and no gating; those stay
> IRA-owned in both modes.

## What still works natively with Cortex off

The default path is `api/routes/chat.py:chat` → `agents.graph.run_graph`
(LangGraph) → `classify` → `biometric_gate` → specialist agent →
`utils.llm.chat_complete` → local Ollama (or vLLM). It never imports
`cortex_bridge`. Confirmed working with the flag off:

- **Owner-gate (router path)** — `router.enforce_owner_gate` is pure Python with
  zero config dependency. Live output:
  ```
  owner=False  q='lock down the network'   -> BLOCK (domain=security)
  owner=True   q='lock down the network'   -> ALLOW (domain=security)
  owner=False  q="what's the weather"      -> ALLOW (domain=None)
  owner=False  q='run a docker command'    -> BLOCK (domain=executor)
  ```
- **Owner-gate (graph path)** — `agents.supervisor.is_restricted_domain` works once
  `Settings` loads (see degradation note). Live output:
  ```
  q='show me the api key'   -> restricted=True
  q='run a docker command'  -> restricted=False
  q="what's the weather"    -> restricted=False
  ```
- **Backend selection** — `_use_cortex()` returns `False`; `config.llm_backend`
  resolves to `ollama`; `utils.llm` routes to the local Ollama client.
- **Classify / route, memory, tools** — all IRA-owned and unchanged by the flag
  (`memory.store`, `agents.supervisor.classify`, the specialist agents). 715
  passing tests exercise these at the default flag value.

## What breaks / degrades — and exactly where

1. **Nothing breaks on the default path**, because OFF *is* the default and the
   legacy LangGraph path is "byte-identical to before" (`chat.py:38`). The Cortex
   path is the opt-in, not the baseline.

2. **The Cortex path itself degrades cleanly when enabled without the binary.**
   Turning the flag on routes chat to `_cortex_route` → `skills/_common.run_skill`
   → `CortexBridge.ask` → `subprocess.run(["cortex", ...])`. With no `cortex` on
   PATH this raises a wrapped, human-readable error rather than crashing:
   ```
   [cortex binary on PATH] = None
   CortexBridge().ask("hello") -> RuntimeError: Cortex executable not found: 'cortex'.
                                   Set IRA_CORTEX_BIN or ensure `cortex` is on PATH.
   ```
   Code path: `cortex_bridge.py:CortexBridge.ask` catches `FileNotFoundError` and
   re-raises `RuntimeError`. So the failure mode of "Cortex on, Cortex missing" is
   a clear refusal, not corruption.

3. **Import coupling (latent, not active on the default path).** Every
   `ira/skills/<name>/__init__.py`, `skills/_common.py`, `subagents/__init__.py`
   and `subagents/architect.py` do `from cortex_bridge import CortexBridge` at
   module top. This is harmless because (a) the default path never imports the
   `skills` package, and (b) importing `CortexBridge` is pure stdlib
   (`subprocess`/`shutil`) — it needs the binary only at `.ask()` call time. But it
   does mean the skills layer is statically bound to the bridge symbol; a future
   second reasoning backend should sit behind an interface rather than a direct
   import (this is exactly what Phase 2 introduces).

4. **Papercut surfaced (feeds Phase 2): the graph gate over-reaches into config.**
   `is_restricted_domain` calls `get_settings()` just to read `owner_name`, which
   forces the *entire* `Settings` model to validate — including `vllm_api_key` —
   even when running on Ollama:
   ```
   ValidationError: 5 validation errors for Settings
     ira_secret_key / ira_admin_password / postgres_password / redis_password / vllm_api_key
       Field required
   ```
   The router gate has no such dependency. So the two gates differ not only in
   *vocabulary* but in *coupling*: one is pure, one drags in all backend secrets.
   Phase 2 fixes the `VLLM_API_KEY`-required-on-Ollama half of this; Phase 3
   unifies the gate so the security decision no longer depends on which path (or
   which secrets) happen to be loaded.

## What Cortex was providing (Y)

- Persona-based skill answers: `ira/skills/<name>/` reasoning produced by the
  `cortex -z` one-shot CLI against a local Ollama, instead of by IRA's LangGraph
  specialist agents.
- 5-agent "Expert Mode" deliberation (`subagents/`, `CortexBridge.deliberate`).
- In all cases: **reasoning text only.** Tools, DB/memory, thread continuity, and
  the owner-gate stay in IRA (`_cortex_route` runs `enforce_owner_gate`, loads
  history from Postgres, and persists the turn itself).

## Decision

Flag left at its default `false` — no code change. The finding is the deliverable.
Phase 2 makes the native-vs-Cortex choice a first-class, interface-backed selection
(`IRA_LLM_BACKEND`) so "Cortex optional" is enforced structurally, not just by a
default env value, and fixes the Ollama/VLLM-key papercut found above.
