# IRA Preprint-Hardening Report — V1 (final)

Branch: `claude/v1-v2-gate-sequence-6ee58p` (cut from `supracloud_ira`).
This file feeds the preprint. It states the result, the evidence, the exact
commands to reproduce, and the remaining gaps — honestly.

## 1. Result in one paragraph

The security spine survived a six-phase hardening pass with **zero regressions**:
every test that passed at baseline still passes. The pass count rose from **715 →
749** purely from new hardening tests. The headline contribution is the
**owner-gate unification**: two independent gate classifiers that previously
disagreed on the same input now share one fail-closed source of truth, proven by a
drift regression test that failed before the change and passes after.

## 2. Test counts vs baseline (spine survived)

| Point | passed | skipped | failed |
|---|---|---|---|
| Baseline (Phase 0) | 715 | 11 | 0 |
| After Phase 2 (reasoning seam) | 726 | 11 | 0 |
| After Phase 3 (gate unification) | 744 | 11 | 0 |
| After Phase 4 (egress defaults) | 749 | 11 | 0 |
| **Final (V1)** | **749** | **11** | **0** |

All 715 baseline tests are still green; the +34 are new hardening tests. No
previously-passing test was edited to go green.

## 3. The Cortex finding (Phase 1)

Boundary, one line: **native IRA does everything; Cortex was an alternative
reasoning engine only.** With `IRA_USE_CORTEX=false` (the default), chat, memory,
classify/route, the owner-gate and tool execution all run on IRA's own LangGraph +
`utils.llm` → Ollama path; Cortex (`cortex -z` CLI) only swaps *who writes the
reasoning text* — it adds no tools, memory or gating. Turning Cortex on without the
binary degrades to a clean `RuntimeError`, never a crash. Full detail and live
output: `docs/CORTEX_DEPENDENCY_FINDING.md`.

Phase 2 made this structural: `ira/reasoning/` exposes a typed `ReasoningBackend`
(`ollama` default / `vllm` / `cortex` / `mock`) selected by `IRA_LLM_BACKEND`, with
per-backend secret validation — and fixed the papercut where `VLLM_API_KEY` was
required even on the Ollama path (now required only when `LLM_BACKEND=vllm`).

## 4. The gate-drift result (Phase 3) — before / after

Same test (`tests/security/test_gate_consistency.py`), unchanged between runs; only
the code under it changed.

**BEFORE** (two classifiers, different vocabularies):
```
7 failed, 4 passed
[run the command: docker ps]    router_blocks=True  graph_blocks=False
[open vs code for me]           router_blocks=True  graph_blocks=False
[show me this week's leads]      router_blocks=True  graph_blocks=False
[architect apply]               router_blocks=True  graph_blocks=False
[show me my credentials]        router_blocks=False graph_blocks=True
[what is my api key for stripe] router_blocks=False graph_blocks=True
[show logs from nginx]          router_blocks=False graph_blocks=True
```

**AFTER** (both paths delegate to `ira/security/owner_gate.py`):
```
11 passed, 0 failed
```

The unified gate returns a typed `GateDecision { allowed, reason, risk_level,
required_role, audit_event_type, domain }`; owner-only is the fail-closed union of
regex intent ∪ `routing.yaml` keywords ∪ owner name. `router.py`,
`agents/supervisor.py` and `agents/graph.py:biometric_gate` all call it; the
duplicated logic is deleted.

## 5. Honest defaults (Phase 4) + README (Phase 5)

External egress is OFF by default: `web_search_enabled=False` (was the only
zero-config lever that left the box), `image_gen_provider="sd_webui"` (local), cloud
tokens empty. `tests/test_egress_defaults.py` proves the default config makes no
external web-search call (provider dispatch explodes if reached) and that opt-in
restores it. The README security table and privacy claim now match
`utils/net_safety.py`, including an explicit **documented residual** row for the
TOCTOU/DNS-rebinding gap (mitigate high-risk fetches with `resolve_pinned()`).

## 6. Reproduce

Run the test suite (lightweight, no Docker):
```
cd supracloud-jarvis/ira
python -m pip install -r requirements-test.txt
python -m pytest tests/ -q                       # expect: 749 passed, 11 skipped
python -m pytest tests/security/ -q              # the gate unification + drift proof
```

Full integration suite (Docker, postgres+redis):
```
cd supracloud-jarvis
make test                                        # scripts/test.sh
```

Run IRA clean-local (local-first default — no cloud/Cortex/vLLM key needed):
```
# minimum env (see supracloud-jarvis/.env.example for the full annotated set):
LLM_BACKEND=ollama        # local Ollama; no VLLM_API_KEY required
IRA_USE_CORTEX=false      # native LangGraph reasoning (default)
WEB_SEARCH_ENABLED=false  # egress off by default
# plus the infra secrets: IRA_SECRET_KEY, IRA_ADMIN_PASSWORD,
# POSTGRES_PASSWORD, REDIS_PASSWORD
```
Native start (Windows): `supracloud-jarvis/start-ira.ps1`. Setup notes:
`supracloud-jarvis/LOCAL_SETUP.md`.

## 7. Gaps stated plainly

- **SSRF TOCTOU/DNS-rebinding residual is real and not globally enforced.**
  `resolve_pinned()` exists but callers must opt in per high-risk fetch; this is the
  one residual the preprint should name explicitly.
- **Skills layer is still statically bound to `cortex_bridge`** at import (every
  `ira/skills/<name>/__init__.py`). Harmless on the default path (never imported),
  but a full second-backend migration of the skills/subagents would route them
  through `ira/reasoning` too. Out of scope for V1.
- **Live model/DB leaves not exercised here.** The container has no Ollama/Postgres/
  Redis, so chat/memory/tool leaves were traced, not invoked; everything above the
  model/DB boundary is exercised by the 749-test suite.
- **`make security` (Bumblebee scan)** is referenced by the repo's separate brief
  and was not run in this V1 pass.

## 8. V1 commit trail (on `claude/v1-v2-gate-sequence-6ee58p`)

```
ec884c1 docs(hardening): record V1 baseline and target file map
ae8b685 docs(hardening): document Cortex-off boundary and dependency finding
7d63d07 feat(reasoning): add typed reasoning-backend seam; fix vLLM-key papercut
8357a81 feat(security): unify the owner-gate into a single source of truth
7bcf5f2 feat(config): default external egress OFF (local-first honest defaults)
9661320 docs(readme): align security table and privacy claim with net_safety reality
```
