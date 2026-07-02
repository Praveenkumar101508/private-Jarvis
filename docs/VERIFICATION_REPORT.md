# SupraCloud IRA — Verification Report

_Phase 7. Environment: Linux, Python 3.11.15 (venv), Node 22.22.2, npm 10.9.7. All
commands run after every change in this release-prep pass (final state)._

## Results

| Command | Result | Pass/Fail | Failure summary | Fix applied / next action |
| --- | --- | --- | --- | --- |
| `pip install -r requirements-test.txt` (venv) | resolved & installed | ✅ Pass | — | (system-pip run failed on Debian-managed PyYAML; venv is the supported path and what CI does) |
| `python -m pytest tests/ -q` (DEV_MODE=true, CI env vars) | **915 passed, 11 skipped** in ~10 s | ✅ Pass | — | — |
| `python -m pytest tests/test_token_revocation.py tests/test_phase5_guards.py` (DEV_MODE **unset** — real auth path) | **21 passed** | ✅ Pass | — | — |
| `python scripts/check_no_push.py <all non-test .py>` | "No literal `git push` found" | ✅ Pass | — | — |
| `pip check` (venv) | no broken requirements | ✅ Pass | — | — |
| `npm ci` (frontend) | clean install | ✅ Pass | — | — |
| `npx tsc --noEmit` | no type errors | ✅ Pass | — | — |
| `npm run build` (Next.js production build) | compiled, 4/4 static pages | ✅ Pass | — | — |
| `npm run lint` | **not run** | ⚠️ Skipped | no ESLint config exists; `next lint` would start interactive setup | next action: commit an `.eslintrc.json` (`"extends": "next/core-web-vitals"`) and add lint to CI |
| `ruff check .` (backend) | 336 findings | ⚠️ Info only | ruff is **not configured** in this repo; findings are dominated by intentional test-file `E402` (219) and unused imports (93) | next action (optional): add a scoped `[tool.ruff]` config, then fix incrementally — mass-fixing without config was judged too invasive for this pass |
| `pip-audit -r requirements-test.txt --no-deps` | **31 known vulns in 9 packages** | ⚠️ Findings | see below | one fix applied; rest documented |
| `npm audit` | 2 vulnerabilities (1 high, 1 moderate) | ⚠️ Findings | Next.js 14.2.35 advisories (DoS/cache-poisoning class) + transitive postcss | fix requires **next@16** (breaking major); deferred — see below |
| `safety` / `gitleaks` | not installed in this environment | ⚠️ Skipped | — | manual secret scan performed instead (regex sweep): no hardcoded secrets found |

## Dependency-vulnerability detail and decisions

**Fixed this pass**
- `python-multipart 0.0.12 → 0.0.31` (both requirements files): clears CVE-2024-53981 and
  six 2026 CVEs. Full suite re-run green after the bump (915 + 21 passed).

**Documented, not fixed (each needs a coordinated framework bump — too risky blind):**
- `starlette 0.41.3` (8 advisories) — pinned by `fastapi==0.115.5`; fixing means a FastAPI
  upgrade. Recommended as its own tested PR.
- `langchain-core / langgraph / langgraph-checkpoint / langsmith / langgraph-sdk` — the
  LangChain stack was pinned as a verified-compatible set (see comments in
  `requirements.txt`); patched versions require re-verifying the whole set together.
- `pytest 8.3.3` (CVE-2025-71176) — dev-only tool, no production exposure.
- `pyasn1 0.4.8` — transitive via python-jose; bump with the auth-stack PR.
- **Next.js 14.2.35** — advisories are mostly DoS/cache-poisoning classes relevant to
  internet-exposed self-hosted deployments; IRA's documented deployment is localhost/LAN
  behind auth, which sharply reduces exposure. Upgrade to Next 15/16 recommended as a
  dedicated roadmap item (it is a breaking major with App Router changes).

**Mitigating context:** IRA is local-first and single-owner; none of these services are
meant to face the public internet, and `DEV_MODE` refuses to start on non-local domains.
This lowers real-world severity but does not remove the upgrade recommendation.

## Verification performed on the UI redesign specifically

- Production build served with `next start`; login page rendered in Chromium at
  1440×900 and 390×844 (screenshots in `assets/screenshots/`), confirming responsive
  layout and the new design system render correctly.
