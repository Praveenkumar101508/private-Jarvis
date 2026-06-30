# IRA Portable — demo-safe profile

What a fresh portable demo enables and disables, and how each is enforced.

## Enabled by default
| Capability | How |
|---|---|
| Chat | core API + local Ollama reasoning |
| Local memory | Postgres + pgvector (`./data/postgres`) |
| Notes (on-disk) | `notes_dir` under the workspace volume |
| Safe workspace file r/w | `./data/workspace` bind only |
| Dashboard / status panel | frontend + `/health`, `/health/detail` |

## Disabled by default
| Capability | How it stays off |
|---|---|
| External web search | `WEB_SEARCH_ENABLED=false` (V1·Phase 4 default; portable guard rail re-asserts) |
| Cloud image / media gen | `IMAGE_GEN_PROVIDER=sd_webui`, empty `REPLICATE_API_TOKEN`/`APIFY_API_TOKEN` |
| Cortex / external reasoning | `IRA_USE_CORTEX=false`, `LLM_BACKEND=ollama` |
| Android actuator | `ANDROID_ACTUATOR_ENABLED=false` (portable guard rail rejects `true`) |
| Shell exec / OS control / business / security ops | owner-gated: the unified `owner_gate` blocks these domains for any non-owner |
| Browser automation, email send, destructive tools | not wired in the portable compose; outbound/destructive actions require the owner-confirmation gate |
| Public LAN exposure | API + frontend published to `127.0.0.1` only; `DEV_MODE=false` |

## Guard rail

`IRA_MODE=portable_demo` refuses to start if any of the above hardened settings is
overridden to an unsafe value (egress on, vLLM/Cortex on, actuator on, dev_mode on,
non-loopback `API_BIND_HOST`). It never loosens a check — see `config.py` and
`tests/portable/test_portable_config.py`.

## Storage layout (all relative — fits on a USB stick)

```
IRA-Portable/
  docker-compose.portable.yml
  portable/            launchers, master-password tools, demo.env.example
  data/                postgres, redis, workspace  (gitignored)
  logs/                                            (gitignored)
  config/              master.enc / master.key      (gitignored)
  models/              pulled Ollama models         (gitignored)
```
