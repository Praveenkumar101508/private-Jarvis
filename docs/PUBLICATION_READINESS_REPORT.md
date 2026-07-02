# SupraCloud IRA — Publication Readiness Report

_Phase 6. Status: **READY WITH TWO OWNER DECISIONS PENDING** (license + internal briefs)._

## Checklist

| Item | Status | Notes |
| --- | --- | --- |
| README.md | ✅ Ready | Title, value prop, features, architecture diagram, privacy model, setup, env vars, run/test commands, real screenshots, security notes, roadmap, maintainer = Praveen Kamineti |
| ARCHITECTURE.md | ✅ Ready | Rewritten this pass to the current Ollama + Cortex reality |
| SECURITY.md | ✅ Ready | Threat model, auth, supported versions, secrets policy, private-report path, honest limitations |
| CONTRIBUTING.md | ✅ Created | Setup, branch workflow, style, test + PR expectations |
| CHANGELOG.md / RELEASE.md | ✅ Ready | Unreleased section documents this release-prep work |
| CITATION.cff | ✅ Created | Author: Praveen Kamineti (alias Praveen Kumar); no license field until one is chosen |
| .env.example | ✅ Safe | Placeholder-only; every variable documented; legacy DB names explained |
| Screenshots/demo | ✅ Improved | Real desktop+mobile captures in `assets/screenshots/`; SVG demo retained; authenticated-view captures need a running backend (instructions in UI report) |
| Tests/CI | ✅ Green | 915 passed / 11 skipped + 21 auth-path tests; `next build` + `tsc` clean (see VERIFICATION_REPORT) |
| Secrets scan | ✅ Clean | No hardcoded secrets found; CI enforces no committed `.env` |
| **LICENSE** | ⚠️ **BLOCKER — owner decision** | See below |
| Internal briefs at root | ⚠️ Owner decision | `CLAUDE.md`, `IRA_INTEGRATION.md`, `AGENTS.md`, `MERGE_PLAN.md` |
| Commit-author hygiene | ⚠️ Known limitation | One historical commit (`9521efd`) has an AI author; `.mailmap` added; full fix requires history rewrite (forbidden) or a fresh publication commit |

## Blocker 1 — LICENSE (the only hard blocker)

There is **no LICENSE file**, and the README correctly states "all rights reserved".
Publishing the repo without a license is legal (source-visible, no reuse rights), but if
you want it to be *used*, pick one. This is a legal decision only you can make — common
options:

- **MIT** — maximum adoption, minimal obligations.
- **Apache-2.0** — like MIT plus an explicit patent grant; matches your vendored
  third-party components (Bumblebee is Apache-2.0).
- **AGPL-3.0** — copyleft; keeps SaaS forks open. Fits a "sovereign AI" ethos.
- **No license (status quo)** — showcase-only; nobody may legally reuse the code.

Once chosen: add `LICENSE` at the root with Praveen Kamineti as copyright holder, update
the README badge (`license-PRIVATE` → the chosen license), and add the `license:` field to
`CITATION.cff`. Nothing in `third_party/` changes — upstream licenses stay as they are.

## Blocker 2 (soft) — internal working documents

`CLAUDE.md`, `IRA_INTEGRATION.md`, `AGENTS.md`, and `MERGE_PLAN.md` are internal process
briefs. They contain nothing secret (verified), but they name development tooling and
read as internal instructions. They were deliberately **not** removed because they drive
your active workflow. Before flipping the repo public, decide: keep (transparent),
move to a private location, or delete in the publication commit.

## Exact commands to run (release flow)

```bash
# 1. Verify from a clean checkout
cd supracloud-jarvis/ira
python -m venv .venv && source .venv/bin/activate && pip install -r requirements-test.txt
DEV_MODE=true IRA_SECRET_KEY=t IRA_ADMIN_PASSWORD=t POSTGRES_PASSWORD=t \
REDIS_PASSWORD=t VLLM_API_KEY=t python -m pytest tests/ -q

cd ../frontend && npm ci && npx tsc --noEmit && npm run build

# 2. Add the LICENSE you chose, then:
git add LICENSE README.md CITATION.cff
git commit -m "chore: add LICENSE"

# 3. Tag the release
git tag -a v1.0.0 -m "SupraCloud IRA 1.0.0 — first public release"
git push origin supracloud_ira --tags
```

## Final release checklist

- [ ] Choose and commit LICENSE (+ README badge + CITATION.cff field)
- [ ] Decide fate of the four internal briefs at root
- [ ] (Optional) rename `supracloud-jarvis/` → `supracloud-ira/` using the procedure in
      `docs/BRANDING_CLEANUP_REPORT.md`
- [ ] (Optional) capture authenticated-app screenshots with the backend running
- [ ] Delete the merged remote branches (commands in `docs/BRANCH_CLEANUP_REPORT.md`)
- [ ] Enable GitHub private vulnerability reporting (Settings → Security)
- [ ] Flip repository visibility to public
- [ ] Create the v1.0.0 GitHub Release using `RELEASE.md` / `CHANGELOG.md` content

## Needs manual review (human judgement)

- License choice (legal).
- Whether the historical AI-authored commit matters for your publication story; if yes,
  the only clean fix is publishing from a fresh initial commit (squash) — trade-off:
  loses public history.
- Real-device pass over the mobile UI (verified at 390×844 in emulation).
