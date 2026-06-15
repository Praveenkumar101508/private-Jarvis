# IRA v1 — Release Notes

**IRA** (Intelligent Responsive Assistant) is a private, sovereign AI assistant that
runs entirely on your own machine. v1 ships the five pillars plus sovereign web
research, behind an owner-gate and a draft→confirm approval flow for anything with
side effects.

## 🧠 What's in v1

- **Brain ↔ Memory** — reasons through the local **Cortex** agent gateway (Ollama
  models), and *remembers*: each conversation carries a stable thread id
  (`X-Cortex-Session-Id`) and a per-owner long-term memory scope
  (`X-Cortex-Session-Key`). An **owner profile** (name / goals / projects /
  preferences) is injected into every turn so it stays grounded in who it serves.
- **Actions** — turns it into an agent, safely. Side-effecting actions (email,
  calendar, file delete) require the **verified owner** *and* an **explicit
  confirmation** (draft → confirm → execute, one-shot tokens). Unconfigured
  integrations **fail soft** with a clear message — they never break the chat.
- **Vision** — sees and reads: a local **vision-language model** (Ollama, e.g.
  `qwen2.5vl`) for images, and a **document reader** (PDF / DOCX / TXT / MD,
  extracted locally).
- **Sovereign web research** — Agent-Reach's pluggable-channel pattern on
  **self-hosted backends only**: SearXNG (search), Crawl4AI (clean web reader),
  yt-dlp, public GitHub, RSS. A **public-only guard** refuses private/internal
  targets and never carries secrets or local files outward; web research is
  owner-gated.
- **Voice** — *(Shadow GPU)* realtime mic → STT (faster-whisper) → brain → TTS
  (Kokoro) → speaker on **LiveKit Agents 1.x**, with a fail-closed **biometric
  owner-gate** and challenge-response for high-stakes actions.
- **Orchestration** — one native launcher (`start-ira.ps1`) brings up the whole
  stack with health checks; `GET /health/detail` reports every pillar independently
  and any one subsystem can drop without taking down the rest.

## 🔒 Sovereignty — nothing leaves the box

Every model and backend is **local / self-hosted**: Ollama for inference, the Cortex
gateway bound to `127.0.0.1`, SearXNG + Crawl4AI for web research. There are **no
cloud LLM, reader, or search SaaS** dependencies. Startup **warns loudly** if the
Cortex URL or a research backend is ever pointed off-box, and the public-only guard
blocks any attempt to send private/internal content outward. Read the public web
freely; private/client data **never** leaves the machine.

## 🚀 Setup

Runs native on Windows (Shadow PC) — no Docker.

```powershell
cd private-Jarvis\supracloud-jarvis
copy .env.example .env          # fill in the secrets + IRA_CORTEX_KEY
# Pull models on the Shadow box:
ollama pull qwen3:14b
ollama pull qwen2.5vl
# (optional web research) run SearXNG (:8888) and Crawl4AI (:11235) locally
pwsh -File .\start-ira.ps1       # brings up the whole stack with health checks
```

Key env (see `.env.example`): `LLM_BACKEND=ollama`, `IRA_USE_CORTEX=true`,
`IRA_CORTEX_URL`/`IRA_CORTEX_KEY`, `OLLAMA_*`, `SEARXNG_URL`/`CRAWL4AI_URL`,
`IRA_ADMIN_USERNAME`/`OWNER_NAME`, and the required secrets.

Verify the build: `cd ira && python -m pytest -q`, and the Definition-of-Done
checklist: `python tests/test_v1_acceptance.py`.

## 🎬 Demo script (2–3 minute video)

1. **Speak to it.** Say *"Good morning, IRA."* — it answers out loud in Kokoro's
   voice (near-realtime).
2. **It knows you.** Your enrolled voice passes the biometric gate → full access. A
   different voice is limited (restricted domains blocked).
3. **It recalls.** Tell it something in turn 1 ("My demo is at 4pm"); two turns later
   ask *"when's my demo again?"* — it remembers (same thread + your memory scope).
4. **It acts, with approval.** *"Draft an email to the team about the launch."* — it
   shows a **draft** and a confirmation token; only after you confirm does it send.
5. **It sees / reads.** Show it an image (*"what's in this picture?"*) and drop in a
   PDF (*"summarize this contract"*) — answers from the local VL model + document
   reader.
6. **It searches — locally.** *"Search the web for the latest on X"* and *"read
   &lt;a public URL&gt;"* — clean results come back via your **self-hosted** SearXNG /
   Crawl4AI. Run `netstat` alongside: traffic goes only to your local services —
   never to a cloud search/reader.

**That's IRA.** Private. It reasons, remembers, acts (safely), sees, reads, and
reaches the public web — all without anything leaving the box.
