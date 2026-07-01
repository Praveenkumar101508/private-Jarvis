# IRA model selection

IRA is **local-first**: it uses the right *local* model for each task instead of
one big model for everything. External frontier APIs are **optional** and
**never called without your explicit consent**.

The system has three small layers, all under `ira/reasoning/`:

| File | Responsibility |
| --- | --- |
| `model_profiles.py` + `config/model_profiles.yaml` | which model name belongs to each mode/profile |
| `model_availability.py` | which models Ollama actually has installed (fail-soft) |
| `model_router.py` | pick the mode for a task, resolve the model, gate the API |

It layers **on top of** the existing reasoning backends (`ollama`/`vllm`/`cortex`/
`mock`) and the `utils.llm` chat path — it does not replace them.

---

## Model modes

| Mode | Purpose |
| --- | --- |
| `local_fast` | quick chat, small summaries, simple Q&A, low-latency replies |
| `local_main` | normal high-quality answers, explanations, planning (default intelligence) |
| `local_reasoning` | deep reasoning, architecture, security analysis, debugging logic, multi-step thinking |
| `local_coding` | code generation/review, repo analysis, refactoring, test generation |
| `local_vision` | images, screenshots, PDFs-as-images, visual UI analysis |
| `memory_embedding` | memory embeddings, RAG, document/long-term-memory retrieval |
| `fallback_tiny` | weak-machine / emergency local response, low-resource mode |

### Routing examples

| Request | Mode |
| --- | --- |
| "summarize this" | `local_fast` / `local_main` |
| "rewrite this email" | `local_main` |
| "debug this code" | `local_coding` |
| "audit my repo" | `local_reasoning` (+ `local_coding`) |
| "design SaaS architecture" | `local_reasoning` |
| "explain this screenshot" | `local_vision` |
| "search my memory/documents" | `memory_embedding` (+ `local_main`) |
| "do a very deep architecture/security refactor" | `local_reasoning`, then **offer** API consent |

---

## Profiles

The active profile is chosen by `IRA_MODEL_PROFILE` (default `balanced_local`).

### `balanced_local` (default — recommended)

```
local_fast        qwen3:8b
local_main        qwen3:14b
local_reasoning   deepseek-r1:14b
local_coding      qwen3-coder-next
local_vision      gemma3:12b
memory_embedding  bge-m3
fallback_tiny     gemma3n:e4b
```

### `low_resource` (weak machines)

```
local_fast        qwen3:4b
local_main        qwen3:8b
local_reasoning   deepseek-r1:8b
local_coding      qwen3-coder-next
local_vision      gemma3:4b
memory_embedding  nomic-embed-text
fallback_tiny     gemma3n:e4b
```

### `strong_local` (capable machines)

```
local_fast        qwen3:8b
local_main        qwen3:14b
local_reasoning   deepseek-r1:32b
local_coding      qwen3-coder-next
local_vision      gemma3:12b
memory_embedding  bge-m3
fallback_tiny     gemma3n:e4b
```

---

## Recommended Ollama pulls

`balanced_local` / `strong_local`:

```bash
ollama pull qwen3:8b
ollama pull qwen3:14b
ollama pull deepseek-r1:14b      # or deepseek-r1:32b for strong_local
ollama pull qwen3-coder-next
ollama pull gemma3:12b
ollama pull bge-m3
ollama pull gemma3n:e4b
```

`low_resource`:

```bash
ollama pull qwen3:4b
ollama pull deepseek-r1:8b
ollama pull qwen3-coder-next
ollama pull gemma3:4b
ollama pull nomic-embed-text
ollama pull gemma3n:e4b
```

You don't have to pull everything — if a preferred model is missing, IRA falls
back to the next available **local** model automatically (see below).

---

## Fallbacks

When the preferred model for a mode is not installed, IRA degrades down a
**local-only** chain — it never silently switches to an external API:

```
local_reasoning -> local_main -> local_fast -> fallback_tiny
local_coding    -> local_main -> local_fast -> fallback_tiny
local_vision    -> local_main -> fallback_tiny
local_main      -> local_fast -> fallback_tiny
local_fast      -> fallback_tiny
memory_embedding-> nomic-embed-text
```

Availability is probed from Ollama's `/api/tags`. If Ollama can't be reached the
probe is **fail-soft and optimistic**: IRA keeps the configured model rather than
overriding it on a transient failure.

---

## API consent behaviour

IRA only *offers* an external frontier model for a **very hard** task, and only
when privacy mode allows it. The selection always stays local until you approve.

When offered, IRA shows:

> IRA can answer this locally, but this request deserves deeper reasoning.
>
> For the strongest result, I can activate Deep Intelligence Mode using an
> external frontier model. This may send the necessary prompt/context to the
> selected API provider and may use paid tokens.
>
> Your privacy stays in your control.
>
> Choose one:
> - Approve Deep Intelligence Mode for this request
> - Continue with Local Mode only
>
> Reply: 'Approve' or 'Local only'.

Rules enforced by `reasoning/api_consent.py` (re-exported from `model_router.py`):

- External API is **never** used by default and **never** called silently.
- A very hard task asks for consent; if you decline, IRA continues with
  `local_reasoning` (or `local_main`).
- Even if you approve, IRA only switches over when the master switch
  `IRA_ALLOW_EXTERNAL_API=true` is set; otherwise it stays local.
- `IRA_PRIVACY_MODE=local_only` disables the offer entirely.

> **File layout.** The consent gate, privacy switches, execution gate, and the
> consent audit hook live in `reasoning/api_consent.py`. `model_router.py` keeps
> the task classifier + local model resolution and **re-exports** every consent
> symbol, so `from reasoning.model_router import apply_consent, run_decision, …`
> (and `from reasoning import …`) keep working unchanged.

---

## Configuration

Set these in your environment (or `.env`). See
`config/model_selection.env.example`.

```bash
IRA_MODEL_PROFILE=balanced_local
IRA_LOCAL_FAST_MODEL=qwen3:8b
IRA_LOCAL_MAIN_MODEL=qwen3:14b
IRA_LOCAL_REASONING_MODEL=deepseek-r1:14b
IRA_LOCAL_CODING_MODEL=qwen3-coder-next
IRA_LOCAL_VISION_MODEL=gemma3:12b
IRA_EMBEDDING_MODEL=bge-m3
IRA_FALLBACK_TINY_MODEL=gemma3n:e4b

IRA_USE_MODEL_ROUTER=true
IRA_ALLOW_EXTERNAL_API=false
IRA_REQUIRE_API_CONSENT=true
IRA_PRIVACY_MODE=local_first
```

These are also registered on `config.Settings` (`ira_model_profile`,
`ira_allow_external_api`, `ira_require_api_consent`, `ira_privacy_mode`,
`ira_use_model_router`) so they get a validated, central home.

### Live wiring

When `IRA_USE_MODEL_ROUTER=true` (default), `utils.llm.chat_complete` resolves the
Ollama model for each tier through this layer instead of the static
`OLLAMA_MODEL_*` names:

| chat tier | mode |
| --- | --- |
| fast | `local_fast` |
| deep | `local_main` |
| reasoning | `local_reasoning` |

Resolution is fail-safe: any error, or a model that isn't installed, falls back to
the legacy `OLLAMA_MODEL_*` value, so the existing chat flow never breaks. The
vision path resolves `local_vision` the same way (but never falls back to a text
model). Set `IRA_USE_MODEL_ROUTER=false` to pin the old static behaviour.

### Deep Intelligence Mode execution (external)

External execution is guarded twice. `apply_consent(approved=True)` only *names* an
external target; actually running it goes through `run_decision(...)`, which raises
`ExternalExecutorNotConfigured` unless **both** `IRA_ALLOW_EXTERNAL_API=true` **and**
an executor has been registered via `register_external_executor()`. No external
executor ships by default — Deep Intelligence Mode is decision-only out of the box
and cannot call out on its own.

### Consent audit log

Every Deep Intelligence Mode consent decision emits a structured
`ConsentAuditEvent` through `record_consent_event()` (in `reasoning/api_consent.py`),
so external-use choices are independently queryable. Events are emitted at five
points:

| `reason_code` | When |
| --- | --- |
| `offered` | `route()` offered Deep Intelligence Mode (consent still pending) |
| `approved` | user approved **and** external is allowed → going external |
| `declined` | user chose Local Mode only |
| `blocked` | user approved but `IRA_ALLOW_EXTERNAL_API=false` → stayed local |
| `unavailable` | an external run was attempted but not executable (gate raised) |

Each event carries **safe metadata only** — `timestamp`, `privacy_mode`,
`selected_mode`, `selected_model`, `consent_required`, `consent_approved`,
`provider` (only when approved), `estimated_cost_level`, and the `reason_code`.
There is **no** field for prompt text or context, and no secret is ever passed in.

By default the hook writes one structured `INFO` log line
(`logging.getLogger("ira.reasoning.consent_audit")`). A host app can forward
events into the full audit/event system by registering a sink:

```python
from reasoning import register_consent_audit_sink
from utils.security_events import emit_event  # example integration target

register_consent_audit_sink(lambda ev: my_audit_backend.write(ev))
```

Sink dispatch is fail-soft — a broken sink is logged and swallowed, never
disturbing routing. `reset_consent_audit_sink()` restores the default log sink.

### How to change models

- **Swap one model:** set its `IRA_*_MODEL` env var — it overrides the profile.
- **Swap the whole stack:** set `IRA_MODEL_PROFILE` to `low_resource`,
  `balanced_local`, or `strong_local`.
- **Edit the catalog:** change `config/model_profiles.yaml` (no code change
  needed). The hardcoded defaults in `model_profiles.py` are the safety net used
  only if the YAML is missing.

### How to keep IRA fully local

- Leave `IRA_ALLOW_EXTERNAL_API=false` (the default) — IRA can still *offer* Deep
  Intelligence Mode, but approving it does nothing because the master switch is
  off.
- Or set `IRA_PRIVACY_MODE=local_only` to suppress the offer entirely. Every
  answer is then served by a local Ollama model.

---

## Using it from code

```python
from reasoning import route, apply_consent, consent_message

decision = route("design a scalable multi-tenant architecture")
# decision.selected_model -> "deepseek-r1:14b" (balanced_local)
# decision.provider       -> "local"

if decision.requires_api_consent:
    show(consent_message())
    final = apply_consent(decision, approved=user_said_yes())
```
