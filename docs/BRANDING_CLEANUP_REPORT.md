# SupraCloud IRA — Branding & Name Cleanup Report

_Phase 5. Target identity: Project **SupraCloud IRA** · Product **IRA** · Built by /
Maintainer **Praveen Kumar / Praveen Kamineti**._

## Terms searched (case-insensitive, whole repo minus node_modules/.git/lockfiles)

`jarvis`, `author`, `creator`, `built by`, `maintainer`, `copyright`, `TODO`, `FIXME`,
`your name`, `example.com`, `placeholder`, `replace-me`, email-address regex sweep,
hardcoded-secret regex sweep, plus the allowed names (`Praveen`, `Kamineti`, `Kumar`,
`SupraCloud`, `IRA`) to verify they are used consistently.

## Findings summary

- **No foreign personal names, template-author names, or copied-project author
  names were found anywhere.** The only personal identity in the repo is Praveen
  Kumar / Praveen Kamineti (both allowed).
- No placeholder emails/domains leaking into public content (`example.com` appears only
  as an intentional *non-local* test value in `test_devmode_guard.py`).
- The old assistant name **"Jarvis"** survived in a handful of internal spots (below).
- One historical commit is authored by an AI tool identity (below).

## Names removed / replaced this pass

| Location | Before | After |
| --- | --- | --- |
| `ira/main.py:64` | `logging.getLogger("jarvis")` | `logging.getLogger("ira")` |
| `ira/main.py:140` | startup log "Jarvis {version} starting up" | "IRA {version} starting up" |
| `ira/config.py:53` | default domain `jarvis.local` | `ira.local` (still `*.local`, so all DEV_MODE locality guards behave identically) |
| `ira/config.py` (2 comments/messages) | `jarvis.local`, `wss://jarvis.yourdomain.com` | `ira.local`, `wss://ira.yourdomain.com` |
| `.env.example:125` | `IRA_DOMAIN=jarvis.local` | `IRA_DOMAIN=ira.local` |
| `ira/memory/store.py:4` | "Jarvis's memory" | "IRA's memory" |
| `postgres/init.sql` | "SupraCloud Jarvis" header, 2 comments, seed row `'Jarvis System Bootstrap'` | "SupraCloud IRA", `'IRA System Bootstrap'` (seed only affects fresh databases) |
| `docker-compose.test.yml` | `POSTGRES_DB: jarvis_test` | `ira_test` (ephemeral tmpfs DB, no data impact) |
| `scripts/test.sh` | `pg_isready -U jarvis -d jarvis_test` | `-U "${POSTGRES_USER:-jarvis}" -d ira_test` |
| `ira/tests/test_devmode_guard.py` | `"jarvis.local"` sample inputs | `"ira.local"` (same `*.local` coverage) |
| `ira/utils/auto_implement.py:33` | comment path `→ private-Jarvis-main/` | `→ <repo root>/` |
| `frontend/app/layout.tsx` | title "IRA", generic description | "SupraCloud IRA — Private, Local-First AI Assistant", branded description naming Praveen Kamineti |
| `.mailmap` | — | added mapping normalizing the one AI-authored commit to Praveen Kamineti (display-level; see risks) |

## Names intentionally preserved (with reasons)

| Name | Where | Why preserved |
| --- | --- | --- |
| `hey_jarvis` | `ira/voice/wakeword.py` | **Third-party model identifier** — the name of openWakeWord's pretrained wake-word model. Renaming breaks model loading. Overridable via `IRA_WAKEWORD_MODEL`. |
| `POSTGRES_USER=jarvis`, `POSTGRES_DB=jarvis_db` | `config.py` defaults, `.env.example`, `docker-compose.portable.yml` | **Data compatibility** — existing Postgres volumes were initialized with this role/db; renaming the defaults would break every running deployment. `.env.example` now documents that fresh installs may use `ira`/`ira_db`. Migration (existing installs): `ALTER USER jarvis RENAME TO ira; ALTER DATABASE jarvis_db RENAME TO ira_db;` then update `.env`. |
| `supracloud-jarvis/` directory name | repo tree, CI paths, scripts, docs | **High-blast-radius rename** — referenced by CI workflows, protected-path tests, compose files, and scripts. Safe procedure if wanted: `git mv supracloud-jarvis supracloud-ira`, then update `.github/workflows/*.yml`, `ira/tests/test_auto_implement_protected_paths.py`, `scripts/*.{sh,ps1}`, `Makefile`, and doc references in one commit, then run the full suite. Deferred for owner decision. |
| "JARVIS from Iron Man" | `ira/agents/grok_personality.py` | Cultural reference to the fictional character as a personality inspiration — not project branding. |
| Jarvis mentions in historical reports | `MERGE_PLAN.md`, `docs/*_REPORT.md`, `ira/docs/HARDENING_*` | Historical records of past work; rewriting history docs would falsify them. |
| Upstream names (Bumblebee/Perplexity, agency-agents, caldav, droidclaw, Ollama, Qwen, LiveKit, etc.) | `third_party/**`, NOTICE/LICENSE files, dependency pins | **Legally required third-party attribution — never remove.** |

## Remaining naming risks

1. **Commit `9521efd`** is authored by `Claude <noreply@anthropic.com>` in pushed history.
   Rewriting it requires a force-push of ~90 commits, which is forbidden by this repo's
   working rules (and would break every clone). Mitigations applied/available:
   `.mailmap` now normalizes it for all local git tooling; GitHub's UI, however, reads the
   raw commit author. If a clean public history is essential, the accepted pattern is a
   fresh orphan/squashed initial commit at publication time — an owner decision.
2. **`supracloud-jarvis/` directory** — the only remaining prominent "jarvis" string;
   rename procedure documented above.
3. `CLAUDE.md`, `IRA_INTEGRATION.md`, `AGENTS.md`, `MERGE_PLAN.md` at the repo root
   reference AI tooling by name. They are process documentation (not ownership branding)
   and drive the active development workflow, so they were **not** deleted — but for a
   public showcase repo you likely want them moved to a private location or removed in
   the publication commit. Owner decision.
