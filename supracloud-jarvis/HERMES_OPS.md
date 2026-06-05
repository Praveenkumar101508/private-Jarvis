# HERMES_OPS.md — Hermes operational runbook & Phase-6 hardening

Hermes runs **out-of-process** (native Windows install under `%LOCALAPPDATA%\hermes`),
behind an OpenAI-compatible gateway on `127.0.0.1:8642`. IRA reaches it ONLY through
`ira/hermes_bridge.py`. This file is the bank-build hardening + upgrade runbook.

## Security posture (verified 2026-06-03)
- **Gateway: `127.0.0.1:8642`, key-gated** (`API_SERVER_ENABLED=true`, `API_SERVER_HOST=127.0.0.1`,
  `API_SERVER_KEY` in `~/.hermes/.env`, never in the repo). ✓ Localhost-only entry point.
- **✓ RESOLVED (Phase 7.1) — Ollama locked to localhost.** `OLLAMA_HOST=127.0.0.1` (was `0.0.0.0`);
  Ollama now binds `127.0.0.1:11434` only. Verified: external LAN IP `10.0.2.10:11434` REFUSED,
  localhost `200`. The raw model is no longer network-reachable. Reproduce: `scripts/harden-gateway.ps1`.
- **No remote push; local apply gated** — `utils/auto_implement.py` never pushes; the
  `git apply → commit → docker restart` pipeline runs ONLY behind an explicit `architect apply`
  (`is_apply_trigger`). Guarded by `tests/test_security_invariants.py`.
- **Red-team/jailbreak skills stripped** for the bank build — `scripts/strip-bank-skills.ps1`
  removes `red-teaming` (godmode) + `mlops/inference/obliteratus` (model safety-removal) to
  `~/.hermes/skills_disabled/`. Re-run after any `hermes` install/update.
- **✓ RESOLVED (Phase 7.1) — reasoning-only gateway profile.** The `api_server` agent now has its
  **entire toolset DISABLED** (zero tools) at the config level (`hermes tools disable --platform
  api_server …`). 7.1 removed the host/exec/network/escape set (file, terminal, code_execution, web,
  browser, delegation, computer_use); **7.3 live verification found the remaining `todo`/`skills`/`memory`
  bled into reasoning** (architect agents referenced a Hermes task list / SKILL.md instead of answering),
  so those were disabled too. Verified by probe (host-file read refused — no tool) and live (architect
  then produced a clean proposal). IRA runs every real tool itself; the `skills/_common.run_skill` prompt
  directive stays as defense-in-depth. Reproduce: `scripts/harden-gateway.ps1`; re-run after any `hermes`
  update (a fresh install resets tool config).

## Vendor freeze (disaster recovery / certified copy)
- `hermes-vendor/CHECKSUMS.txt` pins `hermes-agent==0.15.2` + the wheel sha256.
- `scripts/freeze-hermes-vendor.ps1` (re)downloads + verifies the wheel; the wheel is gitignored
  (kept on-machine, not in git history).

## Upgrade procedure (the "rehearsal")
Because Hermes is **out-of-process and isolated behind the HTTP/OpenAI bridge, a Hermes
version bump requires ZERO changes under `ira/`** — that is the whole point of the boundary:
1. Bump the install: `& "%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe" -m pip install --upgrade hermes-agent==<new>`.
2. Update `hermes-vendor/CHECKSUMS.txt` + `scripts/freeze-hermes-vendor.ps1` (`$pin` + `$expected`).
3. Re-run `scripts/strip-bank-skills.ps1` (a fresh install re-syncs bundled skills).
4. Restart the gateway (`hermes gateway` / the Startup launcher) and run the overlay tests.

`ira/requirements.txt` does NOT contain `hermes-agent`, so the CI (`ci.yml`, which installs
`ira/requirements.txt` + runs the overlay tests) is **unaffected by Hermes version bumps** — the
bridge speaks the stable OpenAI wire protocol, so the overlay tests pass against any 0.15.x
gateway. (Dependabot watches `hermes-agent` only to open release PRs for a deliberate bump.)
A literal `0.15.2 → 0.15.3` rehearsal awaits a real upstream release; the zero-`ira/`-change
guarantee holds by construction.
