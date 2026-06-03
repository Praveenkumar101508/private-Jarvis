# HERMES_OPS.md — Hermes operational runbook & Phase-6 hardening

Hermes runs **out-of-process** (native Windows install under `%LOCALAPPDATA%\hermes`),
behind an OpenAI-compatible gateway on `127.0.0.1:8642`. IRA reaches it ONLY through
`ira/hermes_bridge.py`. This file is the bank-build hardening + upgrade runbook.

## Security posture (verified 2026-06-03)
- **Gateway: `127.0.0.1:8642`, key-gated** (`API_SERVER_ENABLED=true`, `API_SERVER_HOST=127.0.0.1`,
  `API_SERVER_KEY` in `~/.hermes/.env`, never in the repo). ✓ Localhost-only entry point.
- **⚠️ REQUIRED bank-build hardening — Ollama is exposed.** It listens on `::` / `0.0.0.0`
  because the user env `OLLAMA_HOST=0.0.0.0`. That makes the raw model reachable from the
  network, **bypassing the gateway, biometric gate, and router**. For the bank build, set
  `OLLAMA_HOST=127.0.0.1` (`setx OLLAMA_HOST 127.0.0.1`) and restart Ollama. (Left as-is here
  because it is a pre-existing user setting — change deliberately.)
- **No remote push; local apply gated** — `utils/auto_implement.py` never pushes; the
  `git apply → commit → docker restart` pipeline runs ONLY behind an explicit `architect apply`
  (`is_apply_trigger`). Guarded by `tests/test_security_invariants.py`.
- **Red-team/jailbreak skills stripped** for the bank build — `scripts/strip-bank-skills.ps1`
  removes `red-teaming` (godmode) + `mlops/inference/obliteratus` (model safety-removal) to
  `~/.hermes/skills_disabled/`. Re-run after any `hermes` install/update.
- **Reasoning over-reach (known):** the gateway runs the full agent toolset; an 8B/14B model
  sometimes calls a tool instead of reasoning (e.g. the security persona → read `/var/log/auth.log`).
  Mitigated by the no-tools directive in `skills/_common.run_skill` + stripping godmode. A fuller
  fix is a reasoning-only gateway profile (no filesystem/shell tools) — future enhancement.

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
