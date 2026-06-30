# IRA model-routing — verification report

**Audit date:** 2026-06-30
**Scope:** the model-selection / model-routing implementation (PR #51, merged).
**Mode:** read-only audit. No code was modified for this report.
**Branch audited:** `claude/ira-smart-model-selection-yo0ws6` (== merged content).

> **Path note:** the prompt assumed a repo-root `ira/` tree. The IRA app actually
> lives under **`supracloud-jarvis/ira/`** (per `CLAUDE.md`). All paths below are
> relative to that directory. The files are present and equivalent.

---

## Headline answers

| Question | Verdict |
| --- | --- |
| Can the external API be called **without** consent? | **NO** — and stronger: the routing layer contains **no external client at all** (see §5). |
| Does local fallback work? | **YES** — verified by tests (see §4, §6). |
| Is the default mode local-first? | **YES** — `provider="local"`, `IRA_ALLOW_EXTERNAL_API=false`, `IRA_PRIVACY_MODE=local_first` by default. |
| Are model profiles configurable? | **YES** — via `IRA_MODEL_PROFILE`, per-mode `IRA_*_MODEL`, and `config/model_profiles.yaml`. |
| Do the reasoning tests pass? | **YES** — 56/56 (`tests/reasoning`). |
| Is the router wired into the **live** chat flow? | **YES** (fixed) — `utils.llm` resolves Ollama tiers via the router; see "Fixes applied". |

> **Update (fixes applied):** the gaps M1–M4 below have been addressed in a
> follow-up change. See the **"Fixes applied"** section at the end. The original
> audit findings are kept intact above them for the record.

---

## 1. Files inspected

All expected files exist (names match the spec):

| File | Lines | Status |
| --- | --- | --- |
| `reasoning/model_profiles.py` | 287 | ✅ present |
| `reasoning/model_availability.py` | 215 | ✅ present |
| `reasoning/model_router.py` | 399 | ✅ present |
| `reasoning/__init__.py` | (+14) | ✅ exports router |
| `config/model_profiles.yaml` | 71 | ✅ present |
| `config/model_selection.env.example` | 31 | ✅ present |
| `docs/MODEL_SELECTION.md` | 222 | ✅ present |
| `tests/reasoning/test_model_profiles.py` | 131 | ✅ present |
| `tests/reasoning/test_model_availability.py` | 111 | ✅ present (extra) |
| `tests/reasoning/test_model_router.py` | 105 | ✅ present |
| `tests/reasoning/test_model_fallbacks.py` | 95 | ✅ present |
| `tests/reasoning/test_api_consent_gate.py` | 104 | ✅ present |

`git status` is clean; the work is committed. `git diff --stat` vs the merge-base
shows 13 files, +1785 lines, all additive (no existing files rewritten except an
additive change to `reasoning/__init__.py`).

---

## 2. Model profiles — ✅ correct

`config/model_profiles.yaml` defines all three profiles
(`low_resource`, `balanced_local`, `strong_local`) and all seven roles
(`local_fast`, `local_main`, `local_reasoning`, `local_coding`, `local_vision`,
`memory_embedding`, `fallback_tiny`).

`balanced_local` values match the target exactly:

```
local_fast: qwen3:8b
local_main: qwen3:14b
local_reasoning: deepseek-r1:14b
local_coding: qwen3-coder-next
local_vision: gemma3:12b
memory_embedding: bge-m3
fallback_tiny: gemma3n:e4b
```

A hardcoded mirror of the catalog exists in `model_profiles.py`
(`_DEFAULT_PROFILES`) and is used if the YAML is missing/malformed — so the
catalog is editable yet always loadable.

---

## 3. Environment / config integration — ✅ supported, ⚠️ one nuance

All eleven settings are honored by the model-selection layer:

| Setting | Read in | Default |
| --- | --- | --- |
| `IRA_MODEL_PROFILE` | `model_profiles.py` | `balanced_local` |
| `IRA_LOCAL_FAST_MODEL` … `IRA_FALLBACK_TINY_MODEL` | `model_profiles.py` (per-mode override) | profile value |
| `IRA_EMBEDDING_MODEL` | `model_profiles.py` | `bge-m3` |
| `IRA_ALLOW_EXTERNAL_API` | `model_router.py` | `false` ✅ safe |
| `IRA_REQUIRE_API_CONSENT` | `model_router.py` | `true` ✅ safe |
| `IRA_PRIVACY_MODE` | `model_router.py` | `local_first` ✅ safe |

**Nuance (minor):** these are read **directly from the environment** inside the
model-selection modules, not registered as fields on the central
`config.py:Settings` (pydantic) class. They therefore get no pydantic validation
and don't appear in the documented `Settings` surface. Functionally fine and
intentional (keeps the layer dependency-light and testable), but worth knowing:
the old tier names (`OLLAMA_MODEL_FAST/DEEP/REASONING`) and the new `IRA_*` names
are **parallel systems** today (see M1).

---

## 4. Router logic — ✅ correct

`ModelRouteDecision` (frozen dataclass) exposes every required field:
`selected_mode`, `selected_model`, `fallback_model`, `reason`, `confidence`,
`requires_api_consent`, `estimated_cost_level`, `privacy_level`,
`allow_local_fallback` (plus `provider`).

Routing rules verified by tests:

| Input | Routed mode | ✅ |
| --- | --- | --- |
| "hi" / short | `local_fast` | ✅ |
| normal explanation | `local_main` | ✅ |
| "debug this code" | `local_coding` | ✅ |
| "design a scalable architecture" / `think_mode` | `local_reasoning` | ✅ |
| image input (`has_image=True`) | `local_vision` | ✅ |
| memory search (`is_memory_search` / keywords) | `memory_embedding` | ✅ |
| very hard task | `local_reasoning` + `requires_api_consent=True` | ✅ |
| missing model | local fallback chain | ✅ |

Fallback chain (all local, never external):
`reasoning → main → fast → tiny`; `coding → main → fast → tiny`;
`vision → main → tiny`; `embedding → nomic-embed-text`. An **unreachable Ollama
probe is fail-soft** and keeps the preferred model (does not crash, does not
force a downgrade).

---

## 5. API consent safety — ✅ strong (no external client exists)

Repository-wide search for `anthropic`, `claude-`, `api.openai.com`,
`generativelanguage`, `gemini-` outside tests returns **only**
`reasoning/model_router.py` (a placeholder string + the `anthropic` default
*label*) and the env example/docs. **There is no Anthropic/OpenAI-cloud/Gemini
client anywhere in the app.** The `AsyncOpenAI` usage in `utils/llm.py` points at
the local Ollama / self-hosted vLLM OpenAI-compatible endpoint, not a cloud API.

Consequences for safety:

- `route()` **always** returns `provider="local"` — verified for "hi", coding,
  architecture, and the hardest task. ✅
- The **only** way to obtain `provider="external"` is
  `apply_consent(decision, approved=True)` **and** `IRA_ALLOW_EXTERNAL_API=true`.
  A decline → stays local; the master switch off → stays local
  ("disabled by config" in the reason). ✅
- `IRA_PRIVACY_MODE=local_only` suppresses the offer entirely
  (`requires_api_consent=False`). ✅
- Even when a decision is flipped to `provider="external"`, **no code performs a
  network call** — `apply_consent` only sets a model *name*. So external use is
  not merely consent-gated, it is **not implemented end-to-end** (see M2).

Consent message: present verbatim as `CONSENT_MESSAGE` and matches the required
wording ("Deep Intelligence Mode", "Approve", "Local only"). ✅

---

## 6. Test results

```
python -m pytest tests/reasoning -v   →  56 passed in 0.24s
```

Breakdown: `test_model_profiles` 16, `test_model_availability` 9,
`test_model_router` 13, `test_model_fallbacks` 9, `test_api_consent_gate` 9.

Related existing suites (sanity, no regressions):

```
python -m pytest tests/reasoning tests/test_reasoning_backend.py \
  tests/test_yaml_config.py tests/test_config.py tests/test_router.py
  →  110 passed
```

**Full suite not run.** `python -m pytest` collects modules that require heavy,
uninstalled deps (torch, speechbrain, sentence-transformers, livekit-agents,
asyncpg, etc.); the repo ships `requirements-test.txt` precisely to run a
lightweight subset in CI. The model-selection work depends only on the standard
library + PyYAML, so its tests run standalone. CI on PR #51 (`test` +
`Prod requirements resolution gate`) passed before merge.

---

## 7. Ollama availability integration — ✅ graceful

`ollama` is **not installed** in this audit environment (`ollama list` → not
found). The code handles this correctly:

- `model_availability.probe_availability()` catches all errors and returns
  `reachable=False` (fail-soft, never raises). Confirmed live: calling
  `route(...)` here logs one warning ("connection refused") and still returns a
  valid decision with the preferred model.
- `available_or_unknown()` is optimistic on an unreachable probe, so a missing
  Ollama does not force everything down to `fallback_tiny`.
- Successful probes are cached (30s TTL); failures are not cached (fast recovery).

No automatic `ollama pull` is performed anywhere. ✅

---

## 8. Documentation — ✅ complete

`docs/MODEL_SELECTION.md` covers: model modes; recommended Ollama pull commands
(balanced/strong and low_resource); all three profiles; fallback behaviour; API
consent behaviour; how to change models; how to keep IRA fully local; and how to
enable API mode safely (`IRA_ALLOW_EXTERNAL_API=true`). ✅

---

## What is implemented correctly

1. Profiles, roles, and `balanced_local` defaults — exact.
2. Env + YAML configurability with per-mode overrides.
3. Task → mode routing for all documented cases.
4. Local-only fallback chains, fail-soft availability detection.
5. Consent gate: local-first default, never silent, decline-stays-local,
   master-switch enforcement, `local_only` suppression.
6. Required consent message wording.
7. 56/56 reasoning tests; no regressions in adjacent suites.
8. Documentation.

## What is missing

- **M1 (MAJOR — integration gap, not a bug):** the router is **not wired into the
  live request path**. `utils/llm.py:chat_complete` still selects models the old
  way (`cfg.ollama_model_fast/deep/reasoning` via `use_deep`/`use_reasoning`), and
  no agent / `main.py` / API route imports `reasoning.route`. **Effect:** setting
  `IRA_*` env vars or approving consent changes what `route()` *returns* but does
  **not** change what IRA actually sends to Ollama yet. The system is a correct,
  tested library that nothing calls in production.
- **M2 (MEDIUM):** "Deep Intelligence Mode" is not executable end-to-end. On
  approval, `apply_consent` names an external provider/model but there is no
  client to perform the call. This is safe (can't leak) but means the feature is
  a stub awaiting an executor.
- **M3 (MINOR):** `IRA_*` settings are not registered in `config.py:Settings`, so
  they bypass pydantic validation and the central config surface; the new names
  and the legacy `OLLAMA_MODEL_*` names are parallel.
- **M4 (MINOR):** vision routing classifies on `has_image`, but the live vision
  path (`utils/llm.py:vision_complete`) reads `cfg.ollama_vision_model`, not
  `IRA_LOCAL_VISION_MODEL` / the router — same wiring gap as M1.

## What is broken

- Nothing is broken. All tests pass; no crashes; no regressions found. The items
  above are gaps/incompleteness, not defects.

---

## Verdict summary

- External API callable without consent: **NO**
- Local fallback works: **YES**
- Default mode local-first: **YES**
- Model profiles configurable: **YES**
- Router governs live calls today: **NO** (M1)

---

## Commands to run manually

```bash
cd supracloud-jarvis/ira

# Reasoning tests (the relevant suite)
python -m pytest tests/reasoning -v

# Adjacent sanity suites
python -m pytest tests/test_reasoning_backend.py tests/test_yaml_config.py \
                 tests/test_config.py tests/test_router.py -v

# See installed local models (when Ollama is running)
ollama list

# Smoke-test the router by hand
python -c "from reasoning import route; d=route('design a scalable architecture'); \
print(d.selected_mode, d.selected_model, d.provider, d.requires_api_consent)"
```

---

## Recommended fixes — priority order

1. **(Highest, safety-adjacent) Wire the router into the live flow (M1).** Add a
   thin adapter so `utils/llm.py` (or the agent dispatch) calls
   `reasoning.route(...)` to choose the model, and resolves the consent decision
   before any answer. Keep `provider="local"` as the only auto path; surface the
   consent message to the user for `requires_api_consent`. Add an integration
   test proving a real request picks the routed model and that "Local only" keeps
   it local.
2. **Implement or explicitly disable Deep Intelligence Mode execution (M2).**
   Either add a consent-gated external client (only reachable after
   `apply_consent(approved=True)` + master switch) with an adversarial test that
   it is never invoked otherwise, or document it as "decision-only, no executor"
   so expectations are clear.
3. **Register `IRA_*` in `config.py:Settings` (M3)** for validation and a single
   config surface; have the model-selection layer read from `Settings` with the
   current env reads as fallback.
4. **Route the vision path through the router (M4).**
5. **(Nit) Add a `make models-pull` / docs cross-link** so the pull commands are
   one step from the config example.

---

---

## Fixes applied (M1–M4)

All four gaps were fixed in a follow-up change. The original audit above is left
unedited for the record.

| # | Fix | Files | Tests |
| --- | --- | --- | --- |
| **M1** | `utils.llm.chat_complete` now resolves each Ollama tier (fast→`local_fast`, deep→`local_main`, reasoning→`local_reasoning`) through the model-selection layer via `resolve_ollama_model()`. Fail-safe: any error or uninstalled model falls back to the legacy `ollama_model_*`, so the chat flow can't break. Gated by `IRA_USE_MODEL_ROUTER` (default on). | `utils/llm.py` | `tests/test_llm_model_wiring.py` |
| **M2** | Added a runtime execution gate: `run_decision()` runs local decisions locally and refuses external ones with `ExternalExecutorNotConfigured` unless `IRA_ALLOW_EXTERNAL_API=true` **and** an executor was registered via `register_external_executor()`. No executor ships by default → external is decision-only and cannot call out. | `reasoning/model_router.py` | `tests/reasoning/test_model_execution_gate.py` |
| **M3** | Registered `ira_model_profile`, `ira_allow_external_api`, `ira_require_api_consent`, `ira_privacy_mode`, `ira_use_model_router` on `config.Settings` (validated central surface; safe defaults). The light layer still reads env directly so its unit tests stay dependency-free. | `config.py` | `tests/test_model_selection_settings.py` |
| **M4** | Vision path (`_vision_client_and_model`) resolves `local_vision` via `resolve_ollama_vision_model()` — honours `IRA_LOCAL_VISION_MODEL`/profile, keeps the legacy vision model if the preferred one isn't installed, and **never** falls back to a text model. | `utils/llm.py` | `tests/test_llm_model_wiring.py` |

### Post-fix test results

```
python -m pytest tests/reasoning tests/test_llm_model_wiring.py \
                 tests/test_model_selection_settings.py
  →  71 passed

python -m pytest tests/test_config.py tests/test_reasoning_backend.py \
                 tests/test_yaml_config.py tests/test_router.py
  →  all passed (no regressions)
```

`tests/test_vision.py`: the 5 vision-helper tests pass; one route-level test is
skipped here only because the full API auth stack (`fastapi`/`jose`) isn't
installed in this audit environment — it is in CI.

### Behaviour after fixes (unchanged guarantees)

- Default still local-first; `route()` still always returns `provider="local"`.
- External still impossible without explicit approval **and** the master switch
  **and** a registered executor — now enforced at both decision and execution time.
- Setting `IRA_*` env vars / `IRA_MODEL_PROFILE` now changes the model IRA
  actually sends to Ollama (was decision-only before).

---

*The original audit (above the "Fixes applied" section) was read-only. The fixes
section documents subsequent code changes made after explicit approval.*
