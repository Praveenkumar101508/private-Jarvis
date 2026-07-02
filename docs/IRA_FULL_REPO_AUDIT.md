# SupraCloud IRA — Full Repository Audit

_Phase 2 audit of `supracloud_ira` @ `4869034`. Ratings: **Excellent** (keep as-is) ·
**Best** (minor polish) · **Good** (works, needs polish/docs/UX) · **Should Improve**
(not publication-ready as found)._

## 1. Executive summary

SupraCloud IRA is a genuinely strong local-first assistant codebase: 289 Python files, a
915-test suite that passes clean in ~11 s, an unusually disciplined security posture
(consent-gated external APIs, SSRF guards, owner gate, AST-level "no auto-push" CI check,
adversarial prompt-injection tests), and a README that already reads like a public project.

What kept it from publication as found: **no LICENSE file** (badge says "PRIVATE"),
no CONTRIBUTING/CITATION files, a stale ARCHITECTURE.md describing the retired vLLM/Kokoro
stack, residual "Jarvis" branding in runtime defaults and internal names, internal working
briefs (MERGE_PLAN.md, IRA_INTEGRATION.md) sitting at the repo root, a functional but flat
demo UI, and one historical commit with an AI author identity. Most of these are fixed in
this pass; the license choice and history item need owner decisions (see
`docs/PUBLICATION_READINESS_REPORT.md`).

**Verdict: strong engineering, publication-ready after this pass except for the LICENSE
decision.** Final score: **82/100** (justification in §7).

## 2. Feature quality matrix

| Feature / module | Rating | Evidence | Why | Improvement needed | Priority |
| --- | --- | --- | --- | --- | --- |
| Model routing + answer quality (`reasoning/`) | **Excellent** | 12 dedicated test files (`tests/reasoning/`), profiles, availability fallback chains, deterministic verifier | Layered, documented, fully tested, local-only by construction | none material | P3 |
| Security gates (consent, owner gate, SSRF, cmd/prompt safety) | **Excellent** | `reasoning/api_consent.py`, `security/owner_gate.py`, `utils/net_safety.py`, adversarial tests (`test_prompt_injection_guard`, `test_browser_ssrf`, `test_ssrf_consolidation`, `test_gate_consistency`) | Defense-in-depth with tests proving injection payloads can't change behavior | none material | P3 |
| Test suite + CI design | **Excellent** | 115 files; `test.yml` runs suite, re-runs auth tests with DEV_MODE unset, AST no-push check, secrets check; `ci.yml` isolates prod dep resolution | Fast (11 s), meaningful, security-aware CI | add a lint gate once a linter is configured | P2 |
| Config & safety validators (`config.py`) | **Excellent** | DEV_MODE forbidden on non-local domain, loopback-bind checks, pinned deps with rationale comments | Prevents the classic "auth bypass exposed to LAN" mistake | rename `jarvis.*` defaults (done for domain; DB names documented) | P2 |
| Actions surface (`actions/`) | **Best** | email_triage, calendar_dav, notes, drafting; `test_action_gating`, `test_failsoft_actions` | Local-first, every destructive/outbound action confirmation-gated | more end-to-end docs | P2 |
| Deep research engine (`research/`, `channels/`) | **Best** | `deep_research_engine.py`, sanitization before model, `test_research_guard`, `test_research_channels` | Multi-round, fail-soft, injection-tested | source-citation UX in frontend | P2 |
| Memory layer (`memory/`) | **Best** | store + embeddings + reranker + life_graph + decision_journal, `test_phase1_memory`, `test_memory_context` | Ranked/capped/labelled reference-only context | pgvector migration docs | P2 |
| Worker layer (`worker/`) | **Best** | 14 workers, heartbeat + self-healing + backup tests | Quietly solid | per-worker README table | P3 |
| README | **Best** | 574 lines, honest "is/isn't", mermaid diagram, badges | Already publication-grade | license badge accuracy; screenshots are SVG mockups | P1 |
| `.env.example` | **Best** | 205 lines, placeholder-only, every var documented | Safe and educational | `jarvis.local` / DB-name defaults (domain fixed this pass) | P2 |
| Voice layer (`voice/`) | **Good** | dual-engine (browser-native + legacy LiveKit), biometrics, wakeword; imports tested | Works but carries a legacy transport and heavy optional deps | mark LiveKit path clearly legacy; document model downloads | P2 |
| Frontend UI (`frontend/`) | **Good** → redesigned | builds clean, streams SSE, rich modes; visually flat, mode-toggle row overflows on mobile, weak focus states, generic login | Functional but not demo-premium | **redesigned this pass** — see `docs/UI_REDESIGN_REPORT.md` | P1 |
| Mobile companion (`mobile/`) | **Good** | Expo app, push, tasks; off by default | Optional and honest about it | screenshots + store-less install doc | P3 |
| Portable profile (`portable/`) | **Good** | master password, health check, per-OS start scripts, secret-hygiene test | Nice demo story | unify with main setup docs | P3 |
| ARCHITECTURE.md | **Should Improve** → fixed | described retired vLLM/Kokoro/docker-compose.yml stack; README describes Ollama+Cortex | Stale = worse than missing for reviewers | **rewritten this pass** | P0 |
| Publication files (LICENSE, CONTRIBUTING, CITATION.cff) | **Should Improve** → partially fixed | LICENSE absent; badge claims "PRIVATE"; no CONTRIBUTING/CITATION | Blocks public release | CONTRIBUTING + CITATION added; **LICENSE needs owner decision** | P0 |
| Branding consistency | **Should Improve** → fixed where safe | `jarvis` logger name, `jarvis.local` default domain, `jarvis_test` DB, historical dir name `supracloud-jarvis/`, one AI-authored commit | Old assistant name visible in public code | display/template names renamed; runtime DB names + dir name documented with migration steps | P1 |
| Repo hygiene (root working briefs) | **Should Improve** | MERGE_PLAN.md (520 lines), IRA_INTEGRATION.md, CLAUDE.md, AGENTS.md at root | Internal process docs in a public repo confuse reviewers | flagged for owner decision (they drive an active workflow; not deleted) | P1 |
| Lint/format tooling | **Should Improve** | no ruff/black/eslint config; `ruff check` (uncofigured defaults) reports 336 style findings — mostly intentional test-file E402 | No enforced style gate | add a scoped ruff config + CI step (recommended, not imposed here) | P2 |

## 3. File-by-file review (key files)

| Path | Purpose | Rating | Issues | Action |
| --- | --- | --- | --- | --- |
| `supracloud-jarvis/ira/main.py` | app entry | Excellent | logger named `"jarvis"` | renamed to `"ira"` |
| `supracloud-jarvis/ira/config.py` | settings + guards | Excellent | `jarvis.local` default + error text | default → `ira.local` (still `*.local`-safe) |
| `supracloud-jarvis/ira/cortex_bridge.py` | reasoning bridge | Best | none found | keep |
| `supracloud-jarvis/ira/router.py` | routing façade | Best | thin, tested | keep |
| `supracloud-jarvis/ira/agents/graph.py` | LangGraph pipeline | Best | none found | keep |
| `supracloud-jarvis/ira/api/routes/chat.py` | SSE chat | Best | large but cohesive | keep |
| `supracloud-jarvis/frontend/components/ChatInterface.tsx` | chat UI | Good | 1,429-line monolith; mode toggles overflow on small screens; icon buttons lack aria-labels | mobile overflow + a11y fixed; split into subcomponents recommended later (risky to do blind) |
| `supracloud-jarvis/frontend/app/page.tsx` | login + shell | Good | generic login card, no brand presence | redesigned |
| `supracloud-jarvis/frontend/app/globals.css` / `tailwind.config.ts` | design system | Good | minimal tokens, no depth/glass, no focus-visible styling | extended (tokens, aurora background, glass, focus rings, reduced-motion) |
| `supracloud-jarvis/frontend/components/Sidebar.tsx` | nav + backup | Good | plain panels; destructive restore uses `confirm()` (acceptable) | polished |
| `ARCHITECTURE.md` | system doc | Should Improve | stale stack (vLLM/Kokoro/compose file that doesn't exist) | rewritten to current Ollama+Cortex reality |
| `SECURITY.md` | security policy | Good | reporting section thin; checklist good | expanded (reporting, secrets policy, honest claims) |
| `CHANGELOG.md` / `RELEASE.md` | release notes | Good | present, current era covered | kept; release entry added |
| `MERGE_PLAN.md`, `IRA_INTEGRATION.md`, `CLAUDE.md`, `AGENTS.md` | internal briefs | Should Improve | internal process material at public root | left in place deliberately (active workflow); listed as pre-publish decision |
| `docs/*_REPORT.md` (4 pre-existing) | past work reports | Good | internal but harmless, show rigor | keep |
| `security/*.ndjson` | scan output | Good | fine to publish (no secrets — verified) | keep |
| `supracloud-jarvis/.env.example` | env template | Best | `IRA_DOMAIN=jarvis.local` | updated |
| `docker-compose.test.yml` + `scripts/test.sh` | test harness | Good | `jarvis_test` DB name (ephemeral container only) | renamed `ira_test` |
| `supracloud-jarvis/ira/voice/wakeword.py` | wake word | Good | default model `hey_jarvis` is the **upstream openWakeWord pretrained model's name** | keep (third-party identifier, renaming breaks function); documented |
| `.mailmap` | identity normalization | Good | missing map for one legacy AI-authored commit | mapping added |

## 4. Architecture review

**Strengths**
- Clear module boundaries inside `ira/` (agents / reasoning / memory / actions / channels /
  voice / worker) with `cortex_bridge.py` as an explicit anti-corruption layer.
- Local-first is enforced *in code*, not just promised: localhost-bound reasoning engine,
  startup warnings for non-local URLs, consent gate for anything external.
- The answer-quality layer (router → policy → context → verifier) is a real architecture,
  not a prompt pile.
- CI is designed around actual failure modes (prod-dep resolution gate, no-DEV_MODE auth
  re-run, AST push guard).

**Weak points / risks**
- `supracloud-jarvis/` directory name embeds the retired product name; renaming touches CI
  paths, docs, compose — deferred with instructions (see branding report).
- `ChatInterface.tsx` (1.4k lines) concentrates all chat behavior; refactor needs a component
  test harness that doesn't exist yet (no frontend tests at all — the biggest test gap).
- Dual voice transports (browser-native + legacy LiveKit) double the surface; legacy path
  should be quarantined or removed in a future major.
- Scaling: single-owner by design; `future-scale/` exists but is aspirational. Fine for the
  product's honest positioning.
- Maintainability: no lint/format config means style drift; heavy pinned dep tree
  (torch CPU) makes full-prod installs slow — mitigated by the split test requirements.

## 5. Security / privacy review

- **Secrets**: no hardcoded secrets found (pattern scan over repo, excluding tests/docs);
  `.env.example` placeholder-only; CI checks for committed `.env`; portable profile has a
  no-plaintext-secrets test. ✅
- **External APIs**: off by default (`IRA_ALLOW_EXTERNAL_API=false`, `WEB_SEARCH_ENABLED=false`);
  consent-gated with audit logging; optional integrations (Replicate, Apify, Telegram)
  documented as opt-in. ✅
- **Local-first guarantee**: enforced by config validators + startup warnings + tests
  (`test_egress_defaults`, `test_cortex_local_guard`). ✅
- **Consent gates**: destructive/outbound actions confirmation-gated (`test_action_gating`,
  `test_approval_guardrail`). ✅
- **Logging**: consent audit events are metadata-only; no message-content logging found in
  audit paths. ✅
- **Dependency risk**: everything pinned with written rationale; Bumblebee scan records in
  `security/`; no `pip-audit`/`gitleaks` in CI (recommended addition). ⚠️
- **Public-release risk**: DEV_MODE is a full auth bypass — guarded by domain/bind checks and
  prominent warnings, acceptable; Playwright `--no-sandbox` container documented as a known
  limitation; one AI-authored commit in history (identity hygiene, not a security issue). ⚠️

## 6. Publication-readiness review

| Item | Status at audit | Action this pass |
| --- | --- | --- |
| README | strong | badge/license note aligned; screenshots section honest about SVG mockups |
| Install steps | good (native + portable) | kept |
| Screenshots/demo | SVG mockups only | documented how to capture real ones |
| LICENSE | **missing** (badge said PRIVATE) | **owner decision required** — options listed in readiness report |
| SECURITY.md | good | expanded reporting/secrets policy |
| CONTRIBUTING.md | missing | **created** |
| CITATION.cff | missing | **created** (no license field until chosen) |
| Release notes | CHANGELOG + RELEASE present | entry added for this release-prep |
| Env-var docs | excellent (`.env.example`) | jarvis.local default fixed |

## 7. Final score: **82 / 100**

- Engineering quality (code, tests, CI): 34/35
- Security & privacy posture: 18/20
- Documentation: 12/15 (stale ARCHITECTURE.md at audit time; internal briefs at root)
- Publication readiness: 8/15 (no LICENSE/CONTRIBUTING/CITATION at audit time; branding remnants)
- UX / demo quality: 10/15 (functional, flat; no frontend tests)

After this pass everything except the LICENSE decision, the directory-name question, and
frontend tests is addressed; with those done the repo is a ~90+.
