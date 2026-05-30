# IRA — Accuracy Layer

Three levers push the local 14B (Ollama) toward an Opus-like *feel*. They are
**flag-gated and independent of `LLM_BACKEND`** — with every flag at its disabled
value, IRA behaves exactly as the L1–L9 baseline.

| Lever | New? | Where | What it does |
|-------|------|-------|--------------|
| **Reranker** | ✅ added (A2) | `ira/memory/reranker.py`, `ira/memory/store.py` | Re-orders retrieved memories by a cross-encoder for far better precision |
| **Web search** | pre-existing, extended (A3) | `ira/utils/search_tools.py` | Grounds answers in current facts; now provider-switchable + on/off flag |
| **The council** | pre-existing | `ira/agents/expert_mode.py` | 5-agent panel; already fed reranked memory + live search by `chat.py` |

> The reranker improves **both** the normal chat path and Expert Mode, because
> both call `memory.store.retrieve()`.

---

## The flags (in `.env` / `ira/config.py`)

### Reranker — memory precision (default ON)
```
RERANKER_ENABLED=true                    # false => retrieve() = L1-L9 behavior
RERANKER_MODEL=BAAI/bge-reranker-v2-m3   # CPU cross-encoder
RERANKER_DEVICE=cpu                       # keep VRAM free for the 14B
RAG_CANDIDATE_K=20                        # over-fetch this many, rerank, keep RAG_TOP_K
```
How it works: `retrieve()` fetches `RAG_CANDIDATE_K` nearest rows by vector
distance, scores each against the query with the cross-encoder, re-orders, then
applies the existing `RAG_MIN_SIMILARITY` floor and returns `RAG_TOP_K`. It is a
**separate model** — the stored `vector(1024)` embeddings and the DB schema are
never touched (dimension-safe). First run downloads the model (~hundreds of MB).

### Web search — factual grounding (default ON)
```
WEB_SEARCH_ENABLED=true                  # false => no external search calls
WEB_SEARCH_PROVIDER=duckduckgo           # duckduckgo | searxng | tavily | serper
WEB_SEARCH_MAX_RESULTS=5
WEB_SEARCH_TIMEOUT_S=6.0
SEARXNG_URL=http://localhost:8888        # only used when provider=searxng
TAVILY_API_KEY=                          # only used when provider=tavily
SERPER_API_KEY=                          # only used when provider=serper
```
Routing is automatic: `utils/search_tools.should_search()` decides when a query
is time-sensitive (latest/today/current/news/price/who-is/year tokens, etc.).
`get_search_context()` (used by `chat.py`) runs web + X search and injects the
results into context. Failures and the disabled state return `[]` — never a crash.

### The council — deliberation (Expert Mode, opt-in per request)
```
COUNCIL_ENABLED=false                    # reserved for future routed deliberation
COUNCIL_SELF_CONSISTENCY=1               # >1 = sample & reconcile (not yet wired)
COUNCIL_JUDGE_ENABLED=true               # reserved for a future judge pass
```
Expert Mode already runs a 5-agent panel (researcher/critic/executor/creator/
supervisor) and is reached via its own rate-limited endpoint. `chat.py` already
feeds it **reranked memory + live web/X search**, so it is grounded today. The
`COUNCIL_*` flags are placeholders for an optional self-consistency + dedicated
judge pass — **not yet implemented** (decide after testing the 14B's quality;
it is GPU-expensive on a 20 GB A4500 where Ollama serializes generation).

---

## 🔒 Privacy

Web search is the **only** lever that leaves the machine, and **only the query
string is ever sent** — never memory contents or PII.

- **Fully private:** self-host **SearXNG** and set `WEB_SEARCH_PROVIDER=searxng`.
  Quick start (no Docker needed if you run it natively, or use your own host):
  point `SEARXNG_URL` at a running SearXNG with the JSON API enabled
  (`search.formats: [json]` in its `settings.yml`).
- **No account, but external:** `duckduckgo` (default) — queries hit DuckDuckGo.
- **Key-based:** `tavily` / `serper` — best quality, queries go to those APIs.
- **Off:** `WEB_SEARCH_ENABLED=false` — IRA answers from the model + local memory
  only, fully offline.

---

## A/B testing (prove the lift, and the clean rollback)

Everything reverts to the L1–L9 baseline by flipping flags — no redeploy:
```
RERANKER_ENABLED=false
WEB_SEARCH_ENABLED=false
```
Run the same prompts with the flags on vs off and compare. With both off,
`retrieve()` is byte-for-byte the original vector search and no external calls
are made.

---

## GPU budget (20 GB A4500)

- Reranker and embeddings run on **CPU** — they don't compete with the 14B for VRAM.
- On a single A4500 Ollama effectively **serializes** generation, so Expert Mode's
  5-agent fan-out is bounded by `EXPERT_CONCURRENCY` (default 4 — lower to 2 if it
  feels slow). Keep heavy multi-sample deliberation off for everyday chat.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| First memory query is slow | One-time reranker model download/load; it's warmed at startup when `RERANKER_ENABLED=true`. |
| `duckduckgo-search not installed` | `pip install duckduckgo-search` (already pinned in `ira/requirements.txt`). |
| Web results empty / rate-limited | DDG throttles bursts; lower `WEB_SEARCH_MAX_RESULTS`, or switch provider (SearXNG/Tavily/Serper). |
| Want zero external calls | `WEB_SEARCH_ENABLED=false` (offline), or `WEB_SEARCH_PROVIDER=searxng` (self-hosted, private). |
| Memory feels noisy | Raise `RAG_MIN_SIMILARITY`, or raise `RAG_CANDIDATE_K` so the reranker has a wider pool to choose from. |
| Expert Mode too slow | Lower `EXPERT_CONCURRENCY`; keep `COUNCIL_SELF_CONSISTENCY=1`. |

---

## What was verified vs. confirm on the Shadow PC

**Verified during build:** config parses; reranker is gated so `RERANKER_ENABLED=false`
reproduces today's `retrieve()` exactly; web-search default (enabled + duckduckgo)
preserves prior behavior; dimension/DB unchanged.

**Confirm on the Shadow PC:** first-run reranker download; a memory query shows
reranked ordering; a "latest …" query fetches + cites web results; all on Ollama,
no Docker.
