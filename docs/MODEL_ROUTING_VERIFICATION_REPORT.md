# IRA Model Selection & Routing — Verification Report

**Project:** SupraCloud IRA (local-first personal assistant)
**Audit date:** 2026-07-01
**Audit branch:** `claude/ira-model-routing-audit-tx5n4i`
**Scope:** Read-only audit of the existing model-selection / model-routing work. No
application code was changed to produce this report.

---

## 0. Executive summary

The smart model-selection and model-routing feature is **fully implemented, wired into
the live LLM path, documented, and covered by a passing test suite (61 reasoning tests +
2 settings tests = 63 passing).**

The design is genuinely **local-first and consent-gated**:

- `route()` **never** returns an external provider — every routing decision is `local`.
- External ("Deep Intelligence Mode") use requires **all three** of: an explicit user
  approval, the `IRA_ALLOW_EXTERNAL_API` master switch being `true`, **and** a
  host-registered external executor. None of these are on by default.
- Strict privacy mode (`IRA_PRIVACY_MODE=local_only`) suppresses the offer entirely.

**Verdict: SAFE to continue.** No critical safety defects were found. The only gaps are
naming/location differences from the audit checklist (files live under
`supracloud-jarvis/ira/…`, and consent logic lives inside `model_router.py` rather than a
separate `api_consent.py`) and a few minor documentation/observability improvements
listed in §10.

> **Note on file location.** The IRA application lives under `supracloud-jarvis/ira/`
> (per `CLAUDE.md`). All paths in the audit checklist resolve to that subtree — e.g.
> `ira/reasoning/model_router.py` is the real file
> `supracloud-jarvis/ira/reasoning/model_router.py`. A prior copy of this report already
> exists at `supracloud-jarvis/ira/docs/MODEL_ROUTING_VERIFICATION_REPORT.md`; this
> file is the root-level report requested by the audit.

---

## 1. Expected files — presence check

| Expected (checklist) path | Actual path in repo | Status |
| --- | --- | --- |
| `ira/reasoning/model_router.py` | `supracloud-jarvis/ira/reasoning/model_router.py` | ✅ Present (467 lines) |
| `ira/reasoning/model_profiles.py` | `supracloud-jarvis/ira/reasoning/model_profiles.py` | ✅ Present (287 lines) |
| `ira/reasoning/model_availability.py` | `supracloud-jarvis/ira/reasoning/model_availability.py` | ✅ Present (215 lines) |
| `ira/reasoning/api_consent.py` | — | ⚠️ **No separate file.** Consent + privacy + execution gate live inside `model_router.py` (see `apply_consent`, `run_decision`, `register_external_executor`). Functionally complete. |
| `config/model_profiles.yaml` | `supracloud-jarvis/ira/config/model_profiles.yaml` | ✅ Present (71 lines) |
| `docs/MODEL_SELECTION.md` | `supracloud-jarvis/ira/docs/MODEL_SELECTION.md` | ✅ Present (253 lines) |
| `tests/reasoning/test_model_router.py` | `supracloud-jarvis/ira/tests/reasoning/test_model_router.py` | ✅ Present |
| `tests/reasoning/test_model_profiles.py` | `supracloud-jarvis/ira/tests/reasoning/test_model_profiles.py` | ✅ Present |
| `tests/reasoning/test_model_fallbacks.py` | `supracloud-jarvis/ira/tests/reasoning/test_model_fallbacks.py` | ✅ Present |
| `tests/reasoning/test_api_consent_gate.py` | `supracloud-jarvis/ira/tests/reasoning/test_api_consent_gate.py` | ✅ Present |

**Additional related files found (not on the checklist but relevant):**

- `supracloud-jarvis/ira/reasoning/__init__.py` — exports `route`, `apply_consent`, `consent_message`, etc.
- `supracloud-jarvis/ira/config/model_selection.env.example` — documented env template.
- `supracloud-jarvis/ira/tests/reasoning/test_model_availability.py` — Ollama probe tests.
- `supracloud-jarvis/ira/tests/reasoning/test_model_execution_gate.py` — runtime external-execution gate tests.
- `supracloud-jarvis/ira/tests/test_model_selection_settings.py` — proves env vars are wired to `config.Settings`.
- `supracloud-jarvis/ira/tests/test_llm_model_wiring.py` — proves `utils.llm` resolves tiers via the router (not runnable here; see §6).

---

## 2. Model profiles

**All three profiles exist** and are defined both in `config/model_profiles.yaml` and as a
hardcoded safety-net mirror in `model_profiles.py` (`_DEFAULT_PROFILES`):

| Profile | Present |
| --- | --- |
| `low_resource` | ✅ |
| `balanced_local` | ✅ (default) |
| `strong_local` | ✅ |

**All seven model roles/modes exist** as a `ModelMode` enum (`model_profiles.py:60`):
`local_fast`, `local_main`, `local_reasoning`, `local_coding`, `local_vision`,
`memory_embedding`, `fallback_tiny`. ✅

**Expected `balanced_local` models — exact match:**

| Role | Expected | In repo (`config/model_profiles.yaml`) | Match |
| --- | --- | --- | --- |
| local_fast | qwen3:8b | qwen3:8b | ✅ |
| local_main | qwen3:14b | qwen3:14b | ✅ |
| local_reasoning | deepseek-r1:14b | deepseek-r1:14b | ✅ |
| local_coding | qwen3-coder-next | qwen3-coder-next | ✅ |
| local_vision | gemma3:12b | gemma3:12b | ✅ |
| memory_embedding | bge-m3 | bge-m3 | ✅ |
| fallback_tiny | gemma3n:e4b | gemma3n:e4b | ✅ |

A dedicated test (`test_model_profiles.py::test_balanced_local_models`) asserts these exact
values, and `test_every_profile_defines_all_seven_modes` guarantees no profile is missing a
role.

---

## 3. Environment / config settings

All requested settings exist as env vars **and** are connected to the real application
config object `config.Settings` (`supracloud-jarvis/ira/config.py:169–173`), giving them a
validated, central home in addition to being read directly by the reasoning layer.

| Env var | Read by reasoning layer | Bound to `config.Settings` | Notes |
| --- | --- | --- | --- |
| `IRA_MODEL_PROFILE` | ✅ `model_profiles.py:57` | ✅ `ira_model_profile` | default `balanced_local` |
| `IRA_LOCAL_FAST_MODEL` | ✅ (`env_overrides`) | via override map | overrides profile |
| `IRA_LOCAL_MAIN_MODEL` | ✅ | via override map | overrides profile |
| `IRA_LOCAL_REASONING_MODEL` | ✅ | via override map | overrides profile |
| `IRA_LOCAL_CODING_MODEL` | ✅ | via override map | overrides profile |
| `IRA_LOCAL_VISION_MODEL` | ✅ | via override map | overrides profile |
| `IRA_EMBEDDING_MODEL` | ✅ | via override map | overrides profile |
| `IRA_FALLBACK_TINY_MODEL` | ✅ | via override map | overrides profile |
| `IRA_ALLOW_EXTERNAL_API` | ✅ `model_router.py:43` | ✅ `ira_allow_external_api` | default **False** |
| `IRA_REQUIRE_API_CONSENT` | ✅ `model_router.py:44` | ✅ `ira_require_api_consent` | default **True** |
| `IRA_PRIVACY_MODE` | ✅ `model_router.py:45` | ✅ `ira_privacy_mode` | default **local_first** |

Also present: `IRA_USE_MODEL_ROUTER` (default `true`, `config.Settings.ira_use_model_router`)
which controls whether the live `utils.llm` chat path resolves models through the router.

**Safe defaults — confirmed:**

| Setting | Required default | Actual default | OK |
| --- | --- | --- | --- |
| `IRA_ALLOW_EXTERNAL_API` | false | `False` (`external_api_allowed` default, `Settings` default) | ✅ |
| `IRA_REQUIRE_API_CONSENT` | true | `True` (`consent_required` default, `Settings` default) | ✅ |
| `IRA_PRIVACY_MODE` | local_first | `"local_first"` (`DEFAULT_PRIVACY_MODE`, `Settings` default) | ✅ |

Verified by `test_model_selection_settings.py::test_defaults_are_local_first` and
`test_api_consent_gate.py::test_defaults_are_local_first_and_consent_required`.

---

## 4. Model router logic

Routing is done by `classify_task()` → `resolve_model()` → `route()` in `model_router.py`.
Task-type coverage (verified by `test_model_router.py`):

| Task type | Expected mode | Router behaviour | Status |
| --- | --- | --- | --- |
| Simple chat / greeting | local_fast (or local_main) | Short/greeting → `LOCAL_FAST`; else default `LOCAL_MAIN` | ✅ |
| Normal explanation | local_main | Default classification is `LOCAL_MAIN` | ✅ |
| Coding / debugging | local_coding | Coding keywords → `LOCAL_CODING` | ✅ |
| Architecture / security / deep planning | local_reasoning | Reasoning keywords / `think_mode` / long prompt → `LOCAL_REASONING` | ✅ |
| Image / screenshot / PDF | local_vision | `has_image=True` or vision task_type → `LOCAL_VISION` | ✅ |
| Memory / document search | memory_embedding (+ local_main) | Memory keywords / `is_memory_search` → `MEMORY_EMBEDDING` | ✅ |
| Very hard task | recommend external **only after consent** | `very_hard` → `LOCAL_REASONING` locally + `requires_api_consent=True` (never external in `route()`) | ✅ |
| Missing selected model | fall back to another local model | `resolve_model()` walks the local fallback chain | ✅ |

**Route-decision fields — all present** on `ModelRouteDecision` (`model_router.py:98`):

| Required field | Present | Notes |
| --- | --- | --- |
| `selected_mode` | ✅ | resolved `ModelMode` (post-fallback) |
| `selected_model` | ✅ | concrete model name |
| `fallback_model` | ✅ | next local model in chain (or `None`) |
| `reason` | ✅ | human-readable explanation |
| `confidence` | ✅ | 0.0–1.0 from classifier |
| `requires_api_consent` | ✅ | True only for very-hard + privacy allows |
| `estimated_cost_level` | ✅ | `"none"` for local, `"high"` after external approval |
| `privacy_level` | ✅ | the active `IRA_PRIVACY_MODE` |
| `allow_local_fallback` | ✅ | always `True` for local decisions |
| `provider` (bonus) | ✅ | `"local"` \| `"external"` — always `local` from `route()` |

---

## 5. API consent safety

**External-call surface audit.** A repo-wide search for `anthropic`, `openai`, `gemini`,
`api_key`, `frontier`, `external_api`, and Deep Intelligence found:

- **No cloud/frontier client is instantiated anywhere.** All `AsyncOpenAI` clients in
  `utils/llm.py`, `api/routes/multimodal.py`, and `api/routes/video_gen.py` point at
  **local** endpoints — either Ollama (`localhost`, `api_key="ollama"`) or a self-hosted
  vLLM base URL (`cfg.vllm_api_key`, `cfg.vllm_*_url`). None target Anthropic/OpenAI/Gemini
  cloud APIs.
- `frontier` appears **only** as documentation/placeholder text inside
  `register_external_executor()`'s docstring — no frontier client exists.
- The strings `anthropic` / `claude-frontier` appear only in a **test** that supplies a
  fake provider name via env to exercise the approval path — not a real integration.

**Consent guarantees — confirmed (all covered by `test_api_consent_gate.py` /
`test_model_execution_gate.py`):**

| Requirement | Result | Evidence |
| --- | --- | --- |
| External API cannot be called silently | ✅ | `route()` always returns `provider="local"` (`test_route_never_returns_external_provider`) |
| IRA asks before Deep Intelligence Mode | ✅ | `requires_api_consent=True` + `CONSENT_MESSAGE` shown (`test_very_hard_requires_consent_by_default`) |
| "Local only" → answers locally | ✅ | `apply_consent(approved=False)` stays local (`test_decline_continues_locally`) |
| Strict privacy never asks / never calls | ✅ | `IRA_PRIVACY_MODE=local_only` sets `requires_api_consent=False` (`test_local_only_privacy_never_offers_api`) |
| External API disabled by default | ✅ | `IRA_ALLOW_EXTERNAL_API` defaults False; approving without it stays local (`test_approve_without_master_switch_stays_local`) |
| Consent decisions logged / designed to be logged | ⚠️ Partial | The decision is **recorded in `decision.reason`** (e.g. "user chose Local Mode only", "user approved Deep Intelligence Mode → anthropic"), so it is auditable, but there is no dedicated structured/audit-log sink yet. See §10 P4. |
| No API key/secret printed in logs | ✅ | No key material is logged by the reasoning layer; `_external_target()` only reads a provider name + model name, never a key. |

**Defence in depth — runtime execution gate.** Even a hand-crafted `provider="external"`
decision cannot reach the network via `run_decision()` unless **both**
`IRA_ALLOW_EXTERNAL_API=true` **and** an executor was registered with
`register_external_executor()`. No executor ships by default, so Deep Intelligence Mode is
**decision-only out of the box**. Verified by
`test_model_execution_gate.py::test_external_decision_without_executor_raises` and
`::test_external_decision_blocked_when_master_switch_off`.

**Approval message — matches the specified copy.** `CONSENT_MESSAGE`
(`model_router.py:52–62`) is character-for-character equivalent to the requested wording
("IRA can answer this locally, but this request deserves deeper reasoning… Reply: 'Approve'
or 'Local only'."). Asserted by `test_consent_message_is_actionable`.

---

## 6. Fallback safety

Fallback is handled by `resolve_model()` + `fallback_chain()`, walking a **local-only**
chain and picking the first available-or-unknown model. Confirmed by
`test_model_fallbacks.py`:

| Scenario | Behaviour | Test | Status |
| --- | --- | --- | --- |
| `qwen3:14b` (local_main) missing | falls back to `local_fast` | `test_missing_main_falls_back_to_fast` | ✅ |
| `deepseek-r1:14b` (local_reasoning) missing | falls back to `local_main` | `test_missing_reasoning_falls_back_to_main` | ✅ |
| `qwen3-coder-next` (local_coding) missing | degrades `local_coding → local_main → local_fast → fallback_tiny` (chain in YAML) | covered by chain tests | ✅ |
| Nothing installed | lands on terminal `fallback_tiny` (`gemma3n:e4b`) | `test_nothing_installed_still_returns_terminal_tiny` | ✅ |
| Ollama unreachable | fail-soft & optimistic — keeps preferred model, does not crash | `test_unreachable_probe_keeps_preferred_model` | ✅ |
| Fallback never selects external | chain stays local end-to-end | `test_fallback_never_selects_external` | ✅ |
| Embeddings | degrade to lighter embedding model (`nomic-embed-text`), not a chat model | `test_embedding_falls_back_to_lighter_embedding` | ✅ |

Missing Ollama models **do not crash the app**: `model_availability.probe_availability()`
catches every exception and returns `reachable=False`, and `utils.llm.resolve_ollama_model()`
wraps resolution in a `try/except` that returns the legacy static model on any error.

---

## 7. Tests

### Commands run

```bash
python -m pytest tests/reasoning -v
python -m pytest tests/test_model_selection_settings.py -v
python -m pytest tests/test_llm_model_wiring.py -v      # collection error — see below
```

(run from `supracloud-jarvis/ira/`; `pytest`, `pyyaml`, `pydantic`, `pydantic-settings`
were installed into the audit environment first.)

### Results

**`tests/reasoning` — 61 passed, 0 failed, 0 skipped.**

- `test_api_consent_gate.py` — 9 passed
- `test_model_availability.py` — 9 passed
- `test_model_execution_gate.py` — 5 passed
- `test_model_fallbacks.py` — 9 passed
- `test_model_profiles.py` — 16 passed
- `test_model_router.py` — 13 passed

**`tests/test_model_selection_settings.py` — 2 passed** (defaults are local-first; env
overrides are read into `config.Settings`).

**`tests/test_llm_model_wiring.py` — could not run in this audit environment (collection
error, NOT a code defect):**

```
ModuleNotFoundError: No module named 'httpx'
  utils/llm.py:21: in <module>  ->  import httpx
```

This is purely a missing optional dependency in the read-only audit sandbox (`httpx` is a
real runtime dep of `utils.llm`); it is not installed here and installing app runtime deps
was out of scope for a read-only audit. The wiring it exercises is independently confirmed
by reading `utils/llm.py:106` (`resolve_ollama_model`) and `config.py:169–173`.

**Total for the model-routing feature: 63 passed, 0 failed, 1 module un-collectable (env
dependency only).** No heavy/model-invoking tests were run (none exist in this scope — all
tests inject a fake availability snapshot and never call a model).

---

## 8. Documentation

`docs/MODEL_SELECTION.md` **exists** (253 lines) and is thorough. Coverage check:

| Topic | Covered |
| --- | --- |
| `local_fast` | ✅ |
| `local_main` | ✅ |
| `local_reasoning` | ✅ |
| `local_coding` | ✅ |
| `local_vision` | ✅ |
| `memory_embedding` | ✅ |
| `fallback_tiny` | ✅ |
| `low_resource` profile | ✅ |
| `balanced_local` profile | ✅ |
| `strong_local` profile | ✅ |
| API consent behaviour | ✅ (full message + rules) |
| How to keep IRA fully local | ✅ ("How to keep IRA fully local" section) |
| How to enable API mode safely | ✅ (master switch + `register_external_executor` explained) |
| Ollama pull commands | ✅ (per-profile `ollama pull …` blocks) |

---

## 9. Git summary

```
$ git status
On branch claude/ira-model-routing-audit-tx5n4i
(clean working tree before this report was added; the report is the only new file)

$ git diff --stat / --name-only
docs/MODEL_ROUTING_VERIFICATION_REPORT.md   (new file — this report)
```

Recent feature history on the line leading to this audit (all already merged):

```
9005b82 Merge pull request #52 (ira-smart-model-selection)
331db2f docs(reasoning): add model-routing verification report
53d1058 feat(reasoning): wire model router into live flow and gate external execution
6597dbe feat(reasoning): add task-aware model router with consent-gated API
7ad7b5d feat(reasoning): detect installed Ollama models for fallback
9932c8f feat(reasoning): add local-first model profile catalog
```

The model-selection feature is **already committed and merged**; this audit adds only the
report file. No source files were modified.

---

## 10. Final verdict table

| Check | Result | Notes |
| --- | --- | --- |
| External API can be called without consent | **NO** | `route()` is always `local`; external needs approval + master switch + registered executor. |
| Local fallback works | **YES** | Local-only fallback chain; terminates at `fallback_tiny`; fail-soft when Ollama is down. |
| Default mode is local-first | **YES** | `IRA_PRIVACY_MODE=local_first`, `IRA_USE_MODEL_ROUTER=true`, `balanced_local` default. |
| Model profiles are configurable | **YES** | `config/model_profiles.yaml` + per-mode `IRA_*_MODEL` env overrides + `IRA_MODEL_PROFILE`. |
| API disabled by default | **YES** | `IRA_ALLOW_EXTERNAL_API=false` default; approving without it stays local. |
| Strict privacy mode blocks API | **YES** | `IRA_PRIVACY_MODE=local_only` sets `requires_api_consent=False`, never offers. |
| Reasoning tests pass | **YES** | 61/61 in `tests/reasoning` + 2/2 settings tests. |
| Documentation exists | **YES** | `docs/MODEL_SELECTION.md` covers all modes, profiles, consent, local-only, and Ollama pulls. |
| Ready to continue | **YES** | No critical issues; only minor observability/naming polish remains (below). |

---

## 11. Recommended next fixes (prioritized)

### Priority 1 — Critical safety issues
- **None found.** The consent gate, master switch, privacy modes, and runtime execution
  gate are all in place and tested. No action required.

### Priority 2 — Broken tests
- **`tests/test_llm_model_wiring.py` cannot be collected without `httpx`.** This is an
  environment/dependency issue, not a code bug. Fix: ensure `httpx` is in the test/runtime
  requirements (`requirements*.txt` / `pyproject`) and re-run so this test executes in CI
  as well. (Low effort, no code-logic change.)

### Priority 3 — Missing config / docs
- **No standalone `ira/reasoning/api_consent.py`.** The consent/privacy/execution-gate logic
  is complete but lives inside `model_router.py`. If matching the intended module layout
  matters, extract `apply_consent`, `consent_message`, `run_decision`,
  `register_external_executor`, and the privacy/consent env readers into a dedicated
  `api_consent.py` and re-export from `model_router.py` for backward compatibility. Purely
  cosmetic/organizational — behaviour is already correct.
- **Report location.** A copy of this report also exists under
  `supracloud-jarvis/ira/docs/`. Decide on one canonical location to avoid drift.

### Priority 4 — Quality improvements
- **Structured consent audit log.** Consent outcomes are currently recorded only in
  `decision.reason` (human-readable). Add a dedicated audit-log entry (timestamp, task
  hash, privacy mode, approved yes/no, provider) when `apply_consent` / `run_decision` runs,
  so external-use decisions are independently queryable. Ensure it logs **no** prompt content
  or secrets.
- **Consent-required flag is defined but not yet enforced in `route()`.**
  `IRA_REQUIRE_API_CONSENT` is read (`consent_required()`) and defaults `True`, but `route()`
  does not currently branch on it (the offer already always requires explicit approval, so
  behaviour is safe). Consider wiring it so that `IRA_REQUIRE_API_CONSENT=false` +
  `external_ok` privacy could auto-approve — **only if** that product behaviour is ever
  desired; today's always-ask default is the safer stance.
- **Coding-fallback test explicitness.** Add a direct `test_missing_coding_falls_back` case
  mirroring the reasoning/main cases, so the `local_coding` chain has a named regression test
  (the chain is exercised indirectly today).

---

## 12. Follow-up implementation (post-audit)

The minor gaps from §10/§11 have now been addressed. Behaviour of the safety
model is unchanged — external use still requires user approval **plus**
`IRA_ALLOW_EXTERNAL_API=true` **plus** a registered executor — these changes add
structure, tests, and observability around the existing gate.

### 12.1 — `httpx` test dependency (§11 P2) — resolved
`httpx`, `openai`, and `tenacity` (the imports `utils/llm.py` needs, which
`tests/test_llm_model_wiring.py` pulls in) were **already declared** in both
`requirements.txt` and `requirements-test.txt`:

| dep | `requirements.txt` | `requirements-test.txt` |
| --- | --- | --- |
| `httpx==0.27.2` | line 53 | line 10 |
| `openai==1.58.1` | line 8 | line 20 |
| `tenacity==9.0.0` | line 57 | line 45 |

The audit sandbox had only installed `pytest`/`pyyaml`/`pydantic*`, so the module
failed to import — not a repo defect. After `pip install -r requirements-test.txt`
(equivalently the three deps above), the wiring test **runs and passes**:

```
$ python -m pytest tests/test_llm_model_wiring.py -q
........                                                                  [100%]
8 passed
```

No requirements file needed a new entry; the fix is procedural (install the
declared test requirements in CI).

### 12.2 — Structured consent audit log (§11 P4) — added
A dependency-free audit hook now lives in `reasoning/api_consent.py`:
`record_consent_event()` builds a frozen `ConsentAuditEvent` and dispatches it to
a pluggable sink (default: one structured `INFO` line on
`ira.reasoning.consent_audit`; swap via `register_consent_audit_sink()` to feed
the full audit system later). Events fire at all five states — `offered`,
`approved`, `declined`, `blocked`, `unavailable` — and carry **safe metadata
only**: `timestamp`, `privacy_mode`, `selected_mode`, `selected_model`,
`consent_required`, `consent_approved`, `provider` (only when approved),
`estimated_cost_level`, `reason_code`. There is **no** prompt/context field and no
secret is passed in; sink dispatch is fail-soft (a broken sink never disturbs
routing). Covered by the new `tests/reasoning/test_consent_audit.py`, including a
test asserting neither the prompt body nor an embedded secret appears in any event.

### 12.3 — `api_consent.py` extraction (§11 P3) — done
The consent gate, privacy/consent env readers, execution gate, and the new audit
hook were moved into `reasoning/api_consent.py`. `model_router.py` keeps the task
classifier + local model resolution and **re-exports** every consent symbol, so
`from reasoning.model_router import apply_consent, run_decision, …` and
`from reasoning import …` are unchanged (`router.apply_consent is
api_consent.apply_consent`). No circular import: `api_consent` needs no runtime
import of `ModelRouteDecision` (`apply_consent` uses `dataclasses.replace`,
`run_decision` reads attributes). All previously-passing tests still pass.

### 12.4 — Explicit coding-fallback test (§11 P4) — added
`tests/reasoning/test_model_fallbacks.py` gained named regression tests for the
`local_coding` chain: `test_missing_coding_falls_back_to_main`,
`test_missing_coding_and_main_falls_back_to_fast`,
`test_missing_coding_lands_on_terminal_tiny`, and
`test_coding_fallback_never_selects_external` (which asserts every step of the
degraded coding chain stays `provider="local"` and never names an external model).

### 12.5 — Documentation
`docs/MODEL_SELECTION.md` now documents the `api_consent.py` file layout and a
"Consent audit log" section (the five `reason_code`s, the safe-metadata fields,
and how to register a sink). The `IRA_REQUIRE_API_CONSENT` observation from §11 P4
was intentionally **not** changed — today's always-ask default is the safer stance.

### 12.6 — Test results (post-change)

```
$ python -m pytest tests/reasoning tests/test_model_selection_settings.py tests/test_llm_model_wiring.py -q
86 passed
```

Breakdown: 61 (existing reasoning) + 4 (new coding-fallback) + 11 (new consent
audit) = 76 in `tests/reasoning`; 2 settings; 8 wiring. The broader
`python -m pytest -v` still cannot collect 26 unrelated modules in this sandbox
(missing heavy deps: `fastapi`, `numpy`, `langgraph`, `bcrypt`, `redis`) — none of
those touch the reasoning layer and none regressed.

### Updated verdict
| Check | Result |
| --- | --- |
| External API can be called without consent | **NO** (unchanged) |
| Local fallback works | **YES** (now with explicit coding-chain tests) |
| Default mode is local-first | **YES** (unchanged) |
| `httpx` dependency issue | **FIXED** (declared in requirements; wiring test passes) |
| Coding fallback explicit test | **YES** (added) |
| Consent audit logging | **YES** (structured hook + tests) |
| Reasoning tests pass | **YES** (76/76 in `tests/reasoning`) |
| Ready to continue | **YES** |
