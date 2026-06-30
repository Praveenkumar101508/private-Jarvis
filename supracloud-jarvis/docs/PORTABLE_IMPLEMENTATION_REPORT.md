# IRA Portable (V2) — Implementation Report

The portable single-click demo, built ON TOP of the V1-hardened spine — it reuses
V1's egress-off defaults, optional-Cortex backend, and VLLM papercut fix rather than
re-implementing them. Branch: `claude/v1-v2-gate-sequence-6ee58p`.

## What V2 adds

| Phase | Deliverable |
|---|---|
| 1 | `IRA_MODE=portable_demo` guard rail + `portable/demo.env.example` |
| 2 | Master-password gate (`portable/master_password.py` + setup/verify CLIs) |
| 3 | One-command launchers + stop scripts + `portable/health_check.py` |
| 4 | `docker-compose.portable.yml`, `ira/Dockerfile.portable`, demo-safe profile, Demo Mode banner |
| 5 | `portable/BIOMETRIC_AND_VOICE.md`, `IRA_PORTABLE_VOICE_2FA` (off by default) |
| 6 | Portable test suite + this report |

## Per-OS run commands

1. One-time, after mounting the (ideally OS-encrypted) volume:
   ```
   cp portable/demo.env.example portable/.env      # then edit the infra secrets
   python portable/setup_master_password.py --config-dir portable/config
   ```
2. Start (checks deps → loads .env → verifies master password → starts the stack →
   polls /health → opens the browser):
   ```
   Linux    bash portable/start_ira_linux.sh
   macOS    bash portable/start_ira_macos.sh
   Windows  pwsh portable/start_ira_windows.ps1
   ```
3. Stop: `bash portable/stop_ira.sh`  /  `pwsh portable/stop_ira.ps1`

No cloud, Cortex, or vLLM key is required: `LLM_BACKEND=ollama`, `IRA_USE_CORTEX=false`,
egress off. Reasoning runs on the bundled Ollama service.

## Encrypted-bundle steps (honest security model)

The biometric never unlocks the stick directly. Layered path:
1. OS/hardware biometric unlocks an encrypted **volume** (VeraCrypt / BitLocker /
   encrypted APFS / LUKS) — the OS owns the sensor and the key.
2. The IRA **master password** (bcrypt + lockout, encrypted at rest) gates launch.
3. `IRA_MODE=portable_demo` keeps the running system local-first and gated.

Voice is an OPTIONAL second factor (`IRA_PORTABLE_VOICE_2FA=false` default), never a
primary unlock, with an anti-spoof caveat. Full detail:
`portable/BIOMETRIC_AND_VOICE.md`.

## How the security works

- **Guard rail:** `portable_demo` refuses to start if any hardened setting is flipped
  unsafe (egress on, vLLM/Cortex on, actuator on, dev_mode on, non-loopback bind).
- **No LAN exposure:** API and frontend publish to `127.0.0.1` only; `DEV_MODE=false`.
- **Master password:** bcrypt (cost 12) over a SHA-256 pre-hash; record stored only as
  a Fernet-encrypted blob with a 0600 key file; escalating lockout on repeated failures;
  never logged.
- **Owner-gate:** the unified `ira/security/owner_gate.py` (V1·Phase 3) blocks
  owner-only domains (security ops, shell exec, business data, OS control,
  self-modification) for any non-owner — consistently on every path.
- **Self-contained state:** `./data ./logs ./config ./models`, all gitignored.

## Test results

```
tests/portable/   30 passed         (config guard, master password + lockout,
                                      health gate, compose shape, voice 2FA default,
                                      no-plaintext-secrets-in-examples)
full suite        775 passed, 11 skipped, 0 failed
```

## Known limitations

- **Images are config-validated, not build-verified.** This container has no Docker
  daemon, so `docker-compose.portable.yml` was checked with `docker compose config`
  and by structural tests, but the `ira/Dockerfile.portable` / frontend image builds
  were not executed here. Verify the build on a real Docker host before shipping a stick.
- **`ira/Dockerfile` (non-portable) is absent** from the repo though the cloud compose
  references it — pre-existing; the portable stack uses `Dockerfile.portable`.
- **End-to-end boot not exercised here** (no Ollama/Postgres/Redis in this container).
  The launch scripts are syntax-checked and the health gate is unit-tested against
  injected payloads; a real first-run boot should be walked through on target hardware.
- **Voice 2FA is declared, not yet enforced in the live voice pipeline** — the flag and
  the honest model are in place; wiring the additional check into the ECAPA path is a
  follow-up.

## V2 commit trail

```
9092f9f feat(portable): add IRA_MODE=portable_demo guard rail + demo env
3f18c0c feat(portable): add master-password gate with lockout
119f80c feat(portable): add one-command launchers, stop scripts, health gate
6b77fb6 feat(portable): self-contained USB compose, demo-safe profile, demo banner
819f1e4 feat(portable): document OS-backed biometric path; voice 2FA off by default
(this report) docs(portable): portable implementation report + secret-hygiene test
```
