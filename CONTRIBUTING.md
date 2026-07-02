# Contributing to SupraCloud IRA

Thanks for your interest in IRA. This is a personal, local-first project maintained by
**Praveen Kamineti (Praveen Kumar)** — contributions are welcome as issues and small,
focused pull requests.

## Setup

```bash
git clone https://github.com/Praveenkumar101508/Supracloud_ira.git
cd Supracloud_ira/supracloud-jarvis/ira

# Test/dev dependencies (lightweight — what CI uses; no torch)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-test.txt

# Full runtime set (heavy: CPU torch, sentence-transformers)
pip install -r requirements.txt
```

Frontend:

```bash
cd supracloud-jarvis/frontend
npm ci
npm run dev        # http://localhost:3000
```

Runtime configuration: copy `supracloud-jarvis/.env.example` to `supracloud-jarvis/.env`
and fill in every `CHANGE_ME_*` value. **Never commit `.env`.**

## Branch workflow

- `supracloud_ira` is the default/integration branch — all work lands here via PR.
- `ira` is a frozen legacy-codebase archive — never commit to it.
- Branch from `supracloud_ira`, keep PRs small and reviewable, merge back with a normal
  merge commit. **Never force-push shared branches.**

## Code style

- Python: match the existing style — type hints on public functions, docstrings that
  explain *why*, comments only for non-obvious constraints. Dependencies are pinned in
  `requirements*.txt` with a written rationale; keep that discipline.
- TypeScript/React: follow the existing component conventions; Tailwind utility classes;
  no new heavy dependencies without discussion.
- Conventional Commits for messages: `feat(actions): …`, `fix(voice): …`, `docs: …`.

## Test expectations

```bash
cd supracloud-jarvis/ira
DEV_MODE=true IRA_SECRET_KEY=test IRA_ADMIN_PASSWORD=test \
POSTGRES_PASSWORD=test REDIS_PASSWORD=test VLLM_API_KEY=test \
python -m pytest tests/ --tb=short
```

- The suite must stay green (CI runs it on every push/PR, plus an auth-path re-run with
  `DEV_MODE` unset and an AST check that no code auto-pushes to git).
- New features need tests. **Any path that ingests external/web content must include an
  adversarial test** proving an injection payload cannot change IRA's behavior.
- Frontend: `npx tsc --noEmit` and `npm run build` must pass.

## PR expectations

- One logical change per PR, with a clear description of what and why.
- No secrets, tokens, or personal data in code, tests, or fixtures.
- Preserve third-party LICENSE/NOTICE files under `third_party/` — legal requirement.
- Security-relevant changes (auth, gates, egress) should call that out explicitly so they
  get a closer review. See [SECURITY.md](SECURITY.md) for reporting vulnerabilities.
