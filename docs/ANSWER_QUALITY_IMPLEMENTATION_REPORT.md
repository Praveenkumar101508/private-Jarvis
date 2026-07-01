# IRA answer-quality implementation report

**Project:** SupraCloud IRA (local-first personal assistant)
**Scope:** Improve IRA's answer quality (system prompts, task policies,
verification, memory context, honest local fallback) **without** touching
model routing or the external-API consent model, both of which were verified
safe in `docs/MODEL_ROUTING_VERIFICATION_REPORT.md`.

---

## 1. Summary

Added a small, rule-based **answer-quality layer** under
`supracloud-jarvis/ira/reasoning/` that sits on top of the existing model
router (`reasoning/model_router.py`) and consent gate
(`reasoning/api_consent.py`) without modifying either. It shapes *how* IRA
answers (tone per model tier, output structure per task type) and adds a
cheap post-hoc check on drafted answers — no new model calls, no new external
dependency, no change to what is or isn't allowed to leave the machine.

See `supracloud-jarvis/ira/docs/ANSWER_QUALITY_SYSTEM.md` for the full
design writeup.

## 2. Files changed

### New files

| File | Purpose |
| --- | --- |
| `ira/config/model_system_prompts.yaml` | one system-prompt fragment per model tier |
| `ira/reasoning/model_system_prompts.py` | loader for the above (YAML + hardcoded fallback) |
| `ira/reasoning/answer_policy.py` | task-type classifier + output-shape policy + local-fallback framing |
| `ira/reasoning/answer_verifier.py` | rule-based pre-output answer verification |
| `ira/reasoning/memory_context.py` | ranked/bounded/labelled memory context builder |
| `ira/docs/ANSWER_QUALITY_SYSTEM.md` | design documentation |
| `ira/tests/reasoning/test_model_system_prompts.py` | tier-prompt tests |
| `ira/tests/reasoning/test_answer_policy.py` | task-policy tests |
| `ira/tests/reasoning/test_answer_verifier.py` | verifier tests |
| `ira/tests/reasoning/test_memory_context.py` | memory-context tests |
| `ira/tests/reasoning/test_answer_quality_integration.py` | routing/consent-unchanged + end-to-end tests |
| `docs/ANSWER_QUALITY_IMPLEMENTATION_REPORT.md` | this report |

### Modified files

| File | Change |
| --- | --- |
| `ira/reasoning/__init__.py` | re-exports the new public API (`system_prompt_for`, `AnswerPolicy`, `classify_task_type`, `get_policy`, `policy_for_prompt`, `local_fallback_notice`, `VerificationResult`, `verify_answer`, `select_memory_context`) |
| `ira/api/routes/chat.py` | adds `_compose_quality_layer()` (fail-soft, flag-gated on `IRA_USE_MODEL_ROUTER`, skipped for voice) and calls it wherever `system_prompt` is set; replaces the three naive `"\n".join(m["content"] ...)` memory-context joins (main stream handler, architect-proposal trigger, Expert Mode) with `reasoning.memory_context.select_memory_context()` |

No other module was touched. `reasoning/model_router.py`,
`reasoning/api_consent.py`, `reasoning/model_profiles.py`,
`reasoning/model_availability.py`, and `utils/llm.py` are byte-identical to
before this work.

## 3. Prompts added

Six tier-matched fragments in `config/model_system_prompts.yaml` (mirrored as
a hardcoded fallback in `model_system_prompts.py`):
`local_fast`, `local_main`, `local_reasoning`, `local_coding`,
`local_vision`, `fallback_tiny` — see §1 of `ANSWER_QUALITY_SYSTEM.md` for
the full text and rationale of each.

## 4. Policies added

Nine task types in `answer_policy.py`: `rewrite`, `coding`, `architecture`,
`job_application`, `research`, `debugging`, `planning`, `simple_question`,
`general` — each with an `AnswerPolicy` (output instructions +
`requires_citation` / `requires_test_step` flags). Classification is a
first-match keyword table, most-specific task first (`debugging` before the
more generic `coding`, etc.), with no model call.

## 5. Tests run

```
cd supracloud-jarvis/ira
python -m venv <scratch-venv> && pip install -r requirements-test.txt
pytest tests/ -q
```

```
915 passed, 11 skipped in 10.85s
```

(11 skips are pre-existing, environment-gated — e.g. tests needing a live
Postgres/Ollama — unrelated to this change.)

Reasoning-only run:

```
pytest tests/reasoning/ -q
126 passed
```

76 of those are the pre-existing model-routing/consent suite (unchanged,
confirmed still green after the new modules were imported alongside them);
50 are new — 10 tier-prompt, 12 policy, 13 verifier, 9 memory-context, 4
integration (routing/consent unchanged, external still gated, local fallback
still answers, memory stays a separate labelled block).

## 6. Risks / decisions

- **Composition point.** `_compose_quality_layer()` appends tier voice + task
  policy text to the system prompt at three call sites in `chat.py`
  (Engineer mode, Grok mode, and the default skill-persona path). It is
  intentionally **not** wired into the Cortex engine path (`_cortex_route`,
  `IRA_USE_CORTEX=true`) or into voice replies — Cortex builds its own
  prompt outside this router's reach, and voice needs its 1–2 sentence cap
  more than it needs extra guidance text. Both are candidates for a
  follow-up once the Cortex cutover lands.
- **Verifier is report-only.** `verify_answer()` never blocks, rewrites, or
  triggers a second model call by itself — by design, per the brief ("use
  rules first, not another model call by default"). Nothing in `chat.py`
  currently consumes its output; it's exposed via `reasoning` for a host
  app / future worker to call. Wiring it into the live response path (e.g.
  logging a finding, or a supervised regenerate-on-`too_vague`) is a
  reasonable next step but was left out to keep this change small and
  low-risk on the live chat path.
- **Memory-context ranking.** `select_memory_context` ranks by the existing
  `rerank_score`/`similarity` fields (memories already arrive pre-sorted
  from `memory.store.retrieve()`); there is no `created_at` on a memory
  record today, so true recency-weighted ranking isn't implemented yet — the
  function's docstring flags this as the extension point for when that field
  exists, so it can be added without changing the call sites in `chat.py`.
- **Task classification is keyword-based**, same tradeoff as the existing
  `model_router.classify_task` it sits next to — fast and free, not
  semantic. A prompt using unusual phrasing may land in `general` instead of
  a more specific policy; the `general` policy is deliberately conservative
  ("no more structure than the content needs") so a misclassification
  degrades gracefully rather than producing a wrong-shaped answer.

## 7. Acceptance criteria — status

| Criterion | Status |
| --- | --- |
| IRA answers become more consistent and professional | tier + task-policy prompts now shape every non-voice text answer |
| Model routing remains unchanged and safe | `reasoning/model_router.py` untouched; 76 pre-existing routing/consent tests still pass unmodified |
| External API still requires consent | unchanged; verified again in `test_answer_quality_integration.py::test_external_still_requires_approval_and_master_switch` |
| Local models produce better structured answers | tier voice (§1) + task policy (§2) appended to the system prompt before every non-voice generation |
| Tests pass | 915 passed, 11 pre-existing skips, 0 failures |

## 8. Next improvements

- Wire `verify_answer()` findings into the live response path (log-only
  first, e.g. via the existing `security_events`/telemetry seam) before
  considering any auto-regenerate behaviour.
- Extend `memory.store.retrieve()` to return `created_at` so
  `memory_context.select_memory_context` can blend recency into ranking as
  documented.
- Bring `_compose_quality_layer` into the Cortex engine path once that
  cutover is the primary route, so the two engines don't diverge in answer
  shaping.
- Consider a light semantic (embedding-based) task classifier as a fallback
  when the keyword table lands on `general`, still gated behind "rules
  first" — only if keyword misses turn out to be common in practice.
