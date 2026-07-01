# README update report

**Scope:** update the root `README.md` to accurately reflect the merged model-routing,
answer-quality, and consent-gated Deep Intelligence Mode work, without overclaiming.

Source material read before editing:

- `README.md` (previous version)
- `supracloud-jarvis/ira/docs/MODEL_SELECTION.md`
- `docs/MODEL_ROUTING_VERIFICATION_REPORT.md` (canonical audit; the copy under
  `supracloud-jarvis/ira/docs/` says it is superseded by this one)
- `supracloud-jarvis/ira/docs/ANSWER_QUALITY_SYSTEM.md`
- `docs/ANSWER_QUALITY_IMPLEMENTATION_REPORT.md`
- `supracloud-jarvis/ira/config/model_profiles.yaml`
- `supracloud-jarvis/ira/config/model_system_prompts.yaml`
- `supracloud-jarvis/ira/config/model_selection.env.example`
- `supracloud-jarvis/LOCAL_SETUP.md`

Note on paths: the task brief assumed `docs/MODEL_SELECTION.md` and
`config/model_profiles.yaml` at the repo root. The actual files live under
`supracloud-jarvis/ira/docs/` and `supracloud-jarvis/ira/config/` — the README
links point to the real paths.

## Sections changed

- Hero tagline — now mentions task-aware routing and the external-API consent
  gate instead of only "private, sovereign."
- "Why IRA exists" — added a pointer to the model-routing and Deep Intelligence
  Mode sections; kept the local-first claim but scoped it to what's actually true
  (no request leaves the machine _unless you approve it and the master switch is on_).
- New **Key features** section (bullet list of the routing/consent/answer-quality
  capabilities).
- New **What IRA is — and isn't** section.
- **Architecture** — added the two text-pipeline diagrams (normal turn, and the
  Deep-Intelligence-Mode offer path) requested in the brief; the mermaid diagram's
  Ollama node label was corrected from a fixed "Qwen3 8B / 14B" to "model-routed
  local tiers" since routing now varies the model per task.
- New **Model routing** section (profile table, fallback behaviour, router flag).
- New **Deep Intelligence Mode (optional, consent-gated)** section (the three
  required conditions, the verbatim consent message, privacy-mode suppression,
  audit logging).
- New **Answer-quality system** section (tier prompts, 9 task-policy table,
  verifier issue codes, honest local-fallback framing).
- New **Memory safety** section (ranking, capping, dedup, reference-only label).
- **Tech stack** — "Reasoning" bullet now mentions model routing by role instead
  of a fixed Qwen3 8B/14B pair; "Quality" bullet updated to the verified test count.
- **Quick start** — added _Recommended Ollama pulls_, _Environment configuration_,
  and _Testing_ subsections with the real commands from `MODEL_SELECTION.md` and
  the model-selection env example. Added an honest note that setup is currently a
  scripted multi-step process, not one command.
- **Project layout** — added `reasoning/` and `config/` to the `ira/` tree.
- New **Documentation** section linking the four source docs.
- **Roadmap** — added the two completed items (model routing, answer-quality
  layer) and the honest next steps taken from `ANSWER_QUALITY_IMPLEMENTATION_REPORT.md`
  §8 (verifier telemetry wiring, recency-aware memory ranking, Cortex-path
  integration, portable/one-command setup, SaaS multi-tenancy and production
  hardening as later work).

## Claims corrected

- Removed the implication that IRA always uses a fixed Qwen3 8B/14B pair —
  replaced with the actual seven-role router and three swappable profiles.
- Did not add or repeat any "nothing leaves the machine" claim without the
  local-only-mode qualifier; the README now says explicitly that Deep
  Intelligence Mode requires consent **and** a master switch **and** a
  registered executor, and that no executor ships by default.
- Did not describe IRA as banking/retail/enterprise SaaS — added an explicit
  "IRA is not (yet)" section saying so.
- Test-count claim updated from the previous "600+ tests" to the verified
  "915 passed, 11 skipped" from `ANSWER_QUALITY_IMPLEMENTATION_REPORT.md` §5,
  cross-checked against a local run of `tests/reasoning` (126 passed here).
- No AI-tooling attribution, fake screenshots, fake benchmarks, or fake user
  claims were added.

## New features documented

- Model routing (7 roles, 3 profiles, local-only fallback chains).
- Deep Intelligence Mode (three-condition gate, consent message, audit events).
- Answer-quality layer (tier prompts, 9 task policies, rule-based verifier).
- Memory safety (ranked/capped/labelled context).

## Commands added

- `ollama pull ...` sets for `balanced_local`/`strong_local` and `low_resource`.
- Model-selection environment variable block (`IRA_MODEL_PROFILE`,
  `IRA_USE_MODEL_ROUTER`, `IRA_ALLOW_EXTERNAL_API`, `IRA_REQUIRE_API_CONSENT`,
  `IRA_PRIVACY_MODE`, per-role `IRA_*_MODEL` vars).
- `python -m pytest tests/reasoning -v`,
  `python -m pytest tests/test_model_selection_settings.py -v`,
  `python -m pytest tests/test_llm_model_wiring.py -v` (run from
  `supracloud-jarvis/ira/`).

## Links verified

All new/updated README links checked to resolve to files that exist in this
checkout: the four documentation files, `config/model_selection.env.example`,
`requirements-test.txt`, `LOCAL_SETUP.md`, `TAILSCALE_SETUP.md`, `.env.example`,
`start-ira.ps1`, `docker-compose.cloud.yml`, and both `assets/*.svg` images.

## Tests run

```
cd supracloud-jarvis/ira
python -m pytest tests/reasoning -q
→ 126 passed
```

`tests/test_model_selection_settings.py` and `tests/test_llm_model_wiring.py`
were not run in this environment — they import `pydantic`/FastAPI-stack modules
that require installing `requirements-test.txt`, which conflicted with a
system-managed PyYAML package already present in this sandbox and was not
force-installed. Their pass status is taken from
`docs/MODEL_ROUTING_VERIFICATION_REPORT.md` ("Fixes applied" table: 71 passed
across `tests/reasoning`, `test_llm_model_wiring.py`, and
`test_model_selection_settings.py`) and from
`docs/ANSWER_QUALITY_IMPLEMENTATION_REPORT.md` §5 (915 passed, 11 skipped for
the full suite), not re-verified independently here. The README's Testing
section states this honestly rather than claiming a full local re-run.

## Remaining README gaps

- The full `pytest tests/` run (915 passed / 11 skipped) is documented from the
  implementation report, not re-executed in this session — a heavier dependency
  install (`requirements-test.txt`) would be needed to re-verify independently.
- `TAILSCALE_SETUP.md` and `LOCAL_SETUP.md` are Windows/PowerShell-oriented;
  the README does not yet describe a Linux/macOS native (non-Docker) path,
  because none is currently documented in the repo.
- No screenshot/benchmark assets were added, per the brief's explicit
  instruction not to fabricate them — the "See it in action" section still
  points at the existing placeholder SVG with a note for a real recording.
