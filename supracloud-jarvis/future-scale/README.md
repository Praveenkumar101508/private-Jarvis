# future-scale/ — Production / scale assets (dormant)

These files are **not used in local mode**. They were moved here (via `git mv`,
history preserved) during the local/no-Docker migration so the Shadow PC can run
IRA privately on Ollama. Nothing was deleted — when the hardware is upgraded and
IRA goes public, restore them with the steps below.

> All paths are relative to the project root, `supracloud-jarvis/`.

---

## What's archived and why

| Archived path | Original path | What it's for |
|---------------|---------------|---------------|
| `future-scale/docker/docker-compose.yml` | `docker-compose.yml` | Full multi-service stack (api, worker, postgres, redis, vLLM, nginx) |
| `future-scale/docker/Dockerfile` | `ira/Dockerfile` | API container image |
| `future-scale/docker/Dockerfile.worker` | `ira/Dockerfile.worker` | Background worker container image |
| `future-scale/nginx/nginx.conf` | `nginx/nginx.conf` | Reverse proxy + TLS termination + `/api`,`/auth` routing |
| `future-scale/nginx/nginx.conf.template` | `nginx/nginx.conf.template` | Templated nginx config (env-substituted at boot) |
| `future-scale/nginx/docker-entrypoint.sh` | `nginx/docker-entrypoint.sh` | nginx container entrypoint |
| `future-scale/vllm/` | _(empty)_ | Reserved for vLLM model-download / launch scripts (none existed at migration time) |

**Not archived (still active or kept in place):** `ira/` source, `postgres/*.sql`,
`frontend/`, all `scripts/` (Linux `.sh` + the new Windows `.ps1`), and the other
compose files (`docker-compose.cloud.yml`, `docker-compose.test.yml`) which were
left untouched.

The vLLM **engine code** was never moved — it lives dormant in `ira/utils/llm.py`
behind the `LLM_BACKEND` switch (see the bottom of this doc).

---

## How to restore for production

Run from `supracloud-jarvis/`:

```bash
# 1. Move the infra back to where the stack expects it
git mv future-scale/docker/docker-compose.yml  docker-compose.yml
git mv future-scale/docker/Dockerfile          ira/Dockerfile
git mv future-scale/docker/Dockerfile.worker   ira/Dockerfile.worker
git mv future-scale/nginx                       nginx

# 2. Switch the engine back to vLLM (in .env)
#    LLM_BACKEND=vllm
#    VLLM_FAST_URL / VLLM_DEEP_URL / VLLM_REASONING_URL -> your vLLM endpoints
#    VLLM_API_KEY=<real key>

# 3. Point service hosts back at the compose service names (in .env)
#    POSTGRES_HOST=postgres
#    REDIS_HOST=redis
#    (these default to localhost now; envs override them — no code change needed)

# 4. Bring up the stack
docker compose up -d --build
```

> **Note on the compose build context:** `docker-compose.yml` references build
> contexts like `./ira` relative to the project root. The restore above moves the
> compose file **back to the project root**, so those relative paths resolve
> again. If you instead run compose from inside `future-scale/docker/`, fix the
> `build.context` paths (e.g. `../../ira`) first.

After restore, `git status` should show the files as renames (R) back to their
original locations — confirm they match the "Original path" column above.

---

## Hardware ladder (what unlocks what)

| VRAM | Hardware (example) | Model | Backend | Mode |
|------|--------------------|-------|---------|------|
| **20 GB** (now) | RTX A4500 | 14B (e.g. `qwen3:14b`) | **`LLM_BACKEND=ollama`** | Local, private, no Docker — the current Shadow PC setup |
| **48 GB** | 2×3090 / A6000 | up to 70B | Ollama **or** vLLM | Local or small server; can stay Ollama or move to vLLM |
| **80 GB+** | H100 / cloud | vLLM-served (70B+, MoE, R1) | **`LLM_BACKEND=vllm`** + Docker | Public serving with the full Docker/nginx stack restored |

---

## Why switching back is one config change, not a rewrite

The local Ollama path and the vLLM path **coexist in the code** behind the
`LLM_BACKEND` switch (`ira/config.py` + `ira/utils/llm.py`):

- `LLM_BACKEND=ollama` → `ira/utils/llm.py::_use_ollama()` routes every tier to
  the local Ollama endpoint using the `OLLAMA_MODEL_*` names.
- `LLM_BACKEND=vllm` → the original tiered vLLM clients
  (`VLLM_FAST_URL` / `VLLM_DEEP_URL` / `VLLM_REASONING_URL`) are used, unchanged.

So scaling up is: restore the infra (above), flip `LLM_BACKEND` to `vllm`, point
hosts at the container names, and `docker compose up`.
