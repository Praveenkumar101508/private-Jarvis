# IRA — project guide

IRA (private-Jarvis) is a local-first personal assistant. The application lives under
`supracloud-jarvis/ira/` (modules: `voice`, `memory`, `actions`, `agents`, `channels`,
`worker`, `api`, with `router.py` for routing and `cortex_bridge.py` as the cross-module
bridge / anti-corruption layer).

The full multi-phase integration brief is imported below and is authoritative for this work:

@IRA_INTEGRATION.md

## Working rules

- **Branch (R1):** All work happens on `supracloud_ira` only. Confirm `git branch --show-current`
  prints `supracloud_ira` before every commit. Never commit, push, merge, or rebase onto `main`
  or any other branch.
- **Commit identity (R2):** Commits use the configured git author only. Never reference Claude,
  Anthropic, or any AI tool — not in a trailer, body, or title. Conventional Commits style,
  describing the code change only.
- **Licenses (R3):** Keep upstream LICENSE/NOTICE files for any reused third-party code under
  `third_party/<name>/`. This is a legal obligation, separate from R2.
