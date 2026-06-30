# Hardening Baseline — V1·Phase 0

Captured before any code change, on branch `claude/v1-v2-gate-sequence-6ee58p`
(cut from `supracloud_ira`). This file is the number we are protecting: every
later phase must keep the suite green against this baseline, and the security
spine (SSRF guard, auth, prompt-injection isolation, owner-gate) must survive.

## Test baseline

Command (run from `supracloud-jarvis/ira/`):

```
python -m pytest tests/ -q
```

Result:

```
715 passed, 11 skipped, 1 warning in ~5.2s
0 failed
```

- Test files: 82 under `ira/tests/`
- The single warning is a third-party `passlib`/`crypt` DeprecationWarning, not ours.
- Deps installed from `ira/requirements-test.txt` (lightweight CI profile — no
  torch/speechbrain/playwright). The full Docker suite (`scripts/test.sh`) was not
  required to reproduce this count; the unit/collection set is self-contained.

## File map for the four target changes

### 1. The two owner-gates (the drift to unify in Phase 3)

There are **two independent restricted-domain classifiers** with different
vocabularies, so the same input + same user can be gated differently depending on
which path runs.

| | Path A — graph gate | Path B — router gate |
|---|---|---|
| Entry | `agents/graph.py:66` `biometric_gate()` | `router.py:58` `enforce_owner_gate()` |
| Classifier | `agents/supervisor.py:32` `is_restricted_domain()` | `router.py:46` `restricted_domain()` |
| Rule source | `config/routing.yaml` `restricted_keywords:` (l.77) — substring match | `router.py:24` `_RESTRICTED` regex dict |
| Vocabulary | log / password / credential / api key / `.env` phrases | security ops, business/leads, executor (run/exec command), system (open app), architect apply |
| DEV_MODE | bypasses gate entirely (`graph.py:79`) | no DEV_MODE bypass |

Divergence examples (both as a **non-owner**):
- `"run a docker command"` → Path B **BLOCK** (executor regex), Path A **PASS** (no keyword).
- `"show me the api key"` → Path A **BLOCK** (keyword), Path B **PASS** (no regex).

This divergence is the Phase 3 evidence. Phase 3 will introduce
`ira/security/owner_gate.py` as the single source of truth returning a typed
`GateDecision`, replace both paths with calls to it, and ship
`tests/security/test_gate_consistency.py` (failing before, passing after).

### 2. Cortex / `IRA_USE_CORTEX` path (Phase 1 diagnostic, Phase 2 abstraction)

- Flag default OFF: read via `os.getenv("IRA_USE_CORTEX", "false")` in:
  - `agents/cortex_realtime_brain.py:98` (`_use_cortex()`), `:104` deliberation routing
  - `api/routes/chat.py:41` `_USE_CORTEX`
  - `api/routes/health.py:111`
  - `config.py:454` local-only URL guard (`IRA_CORTEX_URL` must be localhost when on)
- Bridge / anti-corruption layer: `cortex_bridge.py` (the repo's Cortex bridge; the
  brief's "Hermes" name maps here).
- Related flags reusing the same mechanism: `IRA_REFLECTION` (`worker/reflection.py`),
  `IRA_HEARTBEAT` (`worker/heartbeat.py`), TTS (`voice/tts_factory.py`).

### 3. Egress switches (Phase 4 honest defaults)

No single `WEB_SEARCH_ENABLED` flag exists yet; egress is spread across provider
settings in `config.py`:
- Apify scraping: `apify_api_token` (l.228), actor IDs (l.231-233)
- Replicate cloud gen: `replicate_api_token` (l.274), `image_gen_provider="replicate"`
  default (l.273), music/bark/sfx models (l.256-265), `flux_model` (l.275)
- HF / model pulls: to be mapped under `config.py` / Ollama bootstrap during Phase 4
- `.env.example`: `supracloud-jarvis/ira/.env.example` (defaults to audit in Phase 4)

Phase 4 will make external egress OFF by default and external tools explicit opt-in,
with a test proving the default config blocks an external call.

### 4. README security table vs `utils/net_safety.py` (Phase 5 honesty)

- Claim to reconcile: `README.md:41` "**nothing leaves your machine unless you wire
  up an integration and turn it on**" and the security table `README.md:123-145`.
- Reality source: `utils/net_safety.py` — `check_url()` (l.90), `is_safe_url()` (l.135),
  `guard_outbound()` (l.151), `resolve_pinned()` (l.169). Documented residual at
  `net_safety.py:18` — **TOCTOU / DNS rebinding**: `is_safe_url()` validates resolved
  IPs but the HTTP client re-resolves at connect time (`resolve_pinned()` is the
  mitigation that must be used to close it). Phase 5 states this residual honestly.

## Branch note

The brief's GLOBAL RULE 1 names `hardening/preprint`; CLAUDE.md R1 names
`supracloud_ira`; the harness designates `claude/v1-v2-gate-sequence-6ee58p` and
forbids pushing elsewhere without explicit permission. Work proceeds on
`claude/v1-v2-gate-sequence-6ee58p` (already tracks origin); `hardening/preprint`
is treated as a logical label. Rename before push is available on request.

## Phase 3 — gate-drift regression evidence (BEFORE)

`tests/security/test_gate_consistency.py` run against pre-Phase-3 code (the two
gate paths still using different vocabularies):

```
7 failed, 4 passed
FAILED ...[run the command: docker ps]   router_blocks=True  graph_blocks=False
FAILED ...[open vs code for me]          router_blocks=True  graph_blocks=False
FAILED ...[show me this week's leads]    router_blocks=True  graph_blocks=False
FAILED ...[architect apply]              router_blocks=True  graph_blocks=False
FAILED ...[show me my credentials]       router_blocks=False graph_blocks=True
FAILED ...[what is my api key for stripe]router_blocks=False graph_blocks=True
FAILED ...[show logs from nginx]         router_blocks=False graph_blocks=True
```

Both directions of drift are present: executor/system/business/architect intents
are blocked only by the router; credentials/api-key/log requests are blocked only
by the graph. The AFTER result (same test, all passing once both paths delegate to
`ira/security/owner_gate.py`) is recorded in `HARDENING_REPORT.md`.

## Phase 0 status

No code changed. Baseline + file map recorded.
