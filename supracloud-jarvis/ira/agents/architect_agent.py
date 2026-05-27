"""
IRA Architect / Evolution Team — Self-Evolving Engineering System.

Runs 24/7 in the background (APScheduler every 12 hours) AND on-demand.
Compares IRA vs Grok/Claude/Gemini/ChatGPT/DeepSeek continuously.
Invents unique new features. Shows full 5-agent visible debate.
Only implements after explicit user approval.

Team:
  Researcher → maps capability gaps vs competing AIs
  Critic     → challenges every idea (risk, complexity, maintenance)
  Executor   → technical feasibility + implementation plan + code sketch
  Creator    → unique features no other AI has yet
  Supervisor → synthesises debate → clean proposal → asks for approval

Background cycle: stored in Redis (architect:latest_proposal)
Notification: Telegram/email when proposal is ready
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import AsyncIterator

from config import get_settings
from utils.llm import chat_complete, stream_tokens

logger = logging.getLogger("ira.architect")

# ─────────────────────────────────────────────────────────────────────────────
# Feature state — what IRA has ✅ vs what is missing ❌
# Updated each time a feature is implemented; Architect tracks this dynamically.
# ─────────────────────────────────────────────────────────────────────────────
IRA_CAPABILITY_MAP = {
    "implemented": [
        "Multi-agent Expert Mode (5 parallel agents)",
        "Real-time X/Twitter search with country+celebrity awareness",
        "Web search + DeepSearch (3-round iterative)",
        "Think Mode (step-by-step reasoning chains)",
        "Image generation (FLUX / Replicate)",
        "Image editing (InstructPix2Pix)",
        "Vision / image analysis (Qwen3-VL)",
        "PDF/DOCX/TXT document upload + analysis",
        "Voice interface (LiveKit + Whisper + Kokoro TTS)",
        "Engineer Mode (4-step code workflow: analysis→plan→diff→verify)",
        "Grok personality + wit mode",
        "Self-healing with git commit",
        "Persistent memory + RAG (BGE embeddings)",
        "Biometric voice verification (ECAPA-TDNN)",
        "Daily backup + restore",
        "Cloud-ready model config (Qwen3 / DeepSeek R1 671B)",
        "Think Mode + Reasoning tier (DeepSeek-R1 endpoint)",
    ],
    "missing": [
        "Video Generation (text→video, image→video) — Grok Imagine Video, Veo 3, Kling 2.6",
        "Advanced Design Tools (UI mockups, Figma prototypes, slides, Canva-style)",
        "Computer Use / Desktop Agent (mouse, keyboard, browser control)",
        "Native Document Creation (PDF, PPTX, Excel, Word from chat)",
        "Video Understanding (upload + analyse video files)",
        "Music / Audio Generation (full songs, voice cloning, SFX)",
        "Deep Research & Long-Form Content Creation mode",
        "Multi-Modal Fusion (text + image + video + audio in one response)",
    ],
    "unique_ira_advantages": [
        "Full privacy — 100% self-hosted, no data leaves your server",
        "Biometric voice gate — only you can access sensitive commands",
        "Self-healing — monitors itself, fixes bugs, commits to git",
        "24/7 Evolution Team — proactively proposes and auto-implements features",
        "Owner-first design — every feature is built for one person's superpower",
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
# Agent system prompts — each agent has a distinct voice and expertise
# ─────────────────────────────────────────────────────────────────────────────

def _researcher_prompt(owner: str, trigger: str) -> str:
    missing = "\n".join(f"  - {f}" for f in IRA_CAPABILITY_MAP["missing"])
    implemented = "\n".join(f"  - {f}" for f in IRA_CAPABILITY_MAP["implemented"][:8])
    return f"""\
You are the RESEARCHER in {owner}'s IRA Evolution Team.

Context: {trigger}

IRA currently has:
{implemented}

Features still missing:
{missing}

Your job RIGHT NOW:
1. Pick the TOP 3 most impactful missing features for {owner}'s personal/business AI use.
2. For each: what does Grok/Claude/Gemini/ChatGPT do, and what gap does IRA have?
3. Be specific — mention real product names, real API availability, real user benefit.
4. Suggest one completely UNIQUE angle that makes IRA's version better than anyone else's.

Respond in exactly this format:
🔬 RESEARCHER:
**Priority 1: [Feature Name]** — [3 sentences: current gap + competitor comparison + unique IRA angle]
**Priority 2: [Feature Name]** — [3 sentences]
**Priority 3: [Feature Name]** — [3 sentences]
Verdict: [Which one would most change {owner}'s daily workflow?]"""


def _creator_prompt(owner: str) -> str:
    return f"""\
You are the CREATOR / VISIONARY in {owner}'s IRA Evolution Team.

You think beyond the obvious. Your job:
1. Invent 2 features that NO OTHER AI currently offers — brand new ideas.
2. These must be buildable with IRA's existing stack (FastAPI + Next.js + vLLM + Docker).
3. They must give {owner} a genuine superpower in their personal/business life.
4. Think about combinations of IRA's unique advantages (voice biometrics + self-healing + memory graph, etc.)

Respond in exactly this format:
✨ CREATOR:
**Invention 1: [Catchy Feature Name]** — [Concept, what makes it unique, how it combines IRA's existing strengths, concrete daily use case]
**Invention 2: [Catchy Feature Name]** — [Concept, what makes it unique, how it combines IRA's existing strengths, concrete daily use case]
Innovation Score: BREAKTHROUGH | HIGH | MEDIUM"""


def _critic_prompt(owner: str) -> str:
    return f"""\
You are the CRITIC / RISK GUARDIAN in {owner}'s IRA Evolution Team.

You have seen what Researcher and Creator proposed. Push back hard and honestly.
For EACH proposed feature (Researcher's top 3 + Creator's 2):
- What is the true implementation complexity? (1=trivial, 10=months)
- What could break in the existing system?
- What is the maintenance burden for a single-person system?
- Is there a 20% effort that gives 80% of the value?
- Should any feature be REJECTED as not worth building right now?

Respond in exactly this format:
🛡️ CRITIC:
**On [Feature 1]:** Complexity [X/10] — [Risk analysis + maintenance concern + recommendation]
**On [Feature 2]:** Complexity [X/10] — [Same]
**On [Feature 3]:** Complexity [X/10] — [Same]
**On [Invention 1]:** Complexity [X/10] — [Feasibility + unique risk]
**On [Invention 2]:** Complexity [X/10] — [Feasibility + unique risk]
Critic's Top Pick: [Which one has best value/effort ratio?]
REJECT List: [Features not worth building now, with brief reason]"""


def _executor_prompt(owner: str) -> str:
    return f"""\
You are the EXECUTOR / LEAD ENGINEER in {owner}'s IRA Evolution Team.

You have seen the Researcher proposals, Creator inventions, and Critic's risk assessment.
Your job: produce a precise, honest technical verdict.

For the top 2 remaining features (after Critic's review):
1. Exact files to create or modify (use real IRA file paths)
2. Libraries needed (are they in requirements.txt already? if not, name them)
3. Does it need a new Docker service? New env vars?
4. How long would it actually take to implement end-to-end?
5. Write a SHORT implementation sketch (pseudo-code or 10-line stub) for the #1 pick.

IRA stack:
  Backend: FastAPI + LangGraph + Python 3.12 (ira/)
  Frontend: Next.js 14 TypeScript (frontend/)
  Models: vLLM Qwen3 3-tier (fast/deep/reasoning)
  DB: PostgreSQL + pgvector, Redis, APScheduler

Respond in exactly this format:
⚙️ EXECUTOR:
**#1 Pick: [Feature Name]**
  Files: [list of ira/ and frontend/ files]
  New libs: [library names + pip install command]
  New services: [yes/no + what]
  Estimate: [X hours]
  Sketch:
  ```python
  [10-15 line stub showing the core logic]
  ```
**#2 Pick: [Feature Name]**
  Files: [list]
  Estimate: [X hours]
Recommendation: [Build #1 first because ...]
Feasibility: READY | NEEDS_PREP | BLOCKED"""


def _supervisor_prompt(owner: str) -> str:
    return f"""\
You are the SUPERVISOR of {owner}'s IRA Evolution Team.

You have read the complete debate between all 4 agents.
Now produce the FINAL PROPOSAL for {owner} to approve or reject.

Required sections (do not skip any):
1. **🏆 Recommendation** — single best feature + one-paragraph justification
2. **📊 Debate Summary** — what each agent said (2-3 lines per agent)
3. **🔍 Feature Details** — full description, how it compares to Grok/Claude/Gemini version
4. **💡 IRA's Unique Angle** — what makes IRA's version special vs the cloud AIs
5. **🛠️ Implementation Plan** — numbered steps (5-8 steps, be specific)
6. **📦 Requirements** — new libs, env vars, Docker changes needed
7. **⏱️ Effort** — realistic hours estimate
8. **⚠️ Risks** — top 2 risks and how to mitigate
9. **🥈 Alternatives** — features #2 and #3 in 2 sentences each

End with EXACTLY this approval block (do not change the wording):

---
**⬇️ AWAITING YOUR DECISION:**
- **Approve & implement:** Reply → `architect implement: [feature name]`
- **See the code first:** Reply → `architect show code: [feature name]`
- **Choose alternative:** Reply → `architect implement: [alternative name]`
- **Reject all:** Reply → `architect next proposal`
---"""


# ─────────────────────────────────────────────────────────────────────────────
# Core debate runner
# ─────────────────────────────────────────────────────────────────────────────

async def _run_agent(
    name: str,
    system: str,
    user_content: str,
    context: str = "",
    max_tokens: int = 1000,
) -> str:
    """Run one architect agent and return its output string."""
    msgs: list[dict] = [{"role": "system", "content": system}]
    if context:
        msgs.append({"role": "system", "content": f"Previous debate:\n{context}"})
    msgs.append({"role": "user", "content": user_content})
    try:
        result = await chat_complete(msgs, use_deep=True, max_tokens=max_tokens, temperature=0.65)
        return result or f"[{name} returned empty]"
    except Exception as e:
        logger.error(f"Architect {name} failed: {e}")
        return f"[{name} error: {e}]"


async def stream_architect_proposal(
    query: str = "Analyse IRA's current capabilities and propose the most valuable next feature.",
    memory_context: str = "",
    background_mode: bool = False,
) -> AsyncIterator[dict]:
    """
    Stream the full 5-agent debate as SSE-compatible dict events.

    background_mode=True: shorter output, no streaming, returns summary for Redis storage.
    """
    cfg = get_settings()
    owner = cfg.owner_name
    t0 = time.monotonic()
    trigger = query if len(query) < 200 else query[:200] + "…"

    user_prompt = (
        f"Perform a complete feature proposal cycle for {owner}'s IRA system.\n"
        f"Context: {trigger}\n"
        + (f"\nMemory context:\n{memory_context}" if memory_context else "")
    )

    # ── Signal debate start ───────────────────────────────────────────────────
    yield {
        "architect_start": True,
        "message": (
            "🏛️ **IRA Evolution Team convening…**\n\n"
            "Five engineers are analysing your system, debating features, and preparing "
            "a ranked proposal. You will see their full discussion in real-time.\n\n"
            "---"
        ),
    }
    await asyncio.sleep(0.02)

    # ── Wave 1: Researcher + Creator in parallel ──────────────────────────────
    yield {"architect_agent": "researcher", "chunk": "\n\n### 🔬 Researcher is analysing the feature landscape…\n\n", "done": False}

    res_task = asyncio.create_task(_run_agent(
        "researcher", _researcher_prompt(owner, trigger), user_prompt, max_tokens=900
    ))
    cre_task = asyncio.create_task(_run_agent(
        "creator", _creator_prompt(owner), user_prompt, max_tokens=700
    ))

    researcher_out, creator_out = await asyncio.gather(res_task, cre_task, return_exceptions=True)
    if isinstance(researcher_out, Exception):
        researcher_out = f"[Researcher error: {researcher_out}]"
    if isinstance(creator_out, Exception):
        creator_out = f"[Creator error: {creator_out}]"

    for line in str(researcher_out).split("\n"):
        yield {"architect_agent": "researcher", "chunk": line + "\n", "done": False}
        await asyncio.sleep(0.004)
    yield {"architect_agent": "researcher", "chunk": "", "done": True}

    yield {"architect_agent": "creator", "chunk": "\n\n### ✨ Creator is inventing unique features…\n\n", "done": False}
    for line in str(creator_out).split("\n"):
        yield {"architect_agent": "creator", "chunk": line + "\n", "done": False}
        await asyncio.sleep(0.004)
    yield {"architect_agent": "creator", "chunk": "", "done": True}

    # ── Wave 2: Critic + Executor in parallel (have Wave 1 context) ──────────
    wave1_ctx = f"RESEARCHER OUTPUT:\n{researcher_out}\n\nCREATOR OUTPUT:\n{creator_out}"

    yield {"architect_agent": "critic", "chunk": "\n\n### 🛡️ Critic is reviewing risks and pushing back…\n\n", "done": False}

    crit_task = asyncio.create_task(_run_agent(
        "critic", _critic_prompt(owner), user_prompt, context=wave1_ctx, max_tokens=900
    ))
    exec_task = asyncio.create_task(_run_agent(
        "executor", _executor_prompt(owner), user_prompt, context=wave1_ctx, max_tokens=1000
    ))

    critic_out, executor_out = await asyncio.gather(crit_task, exec_task, return_exceptions=True)
    if isinstance(critic_out, Exception):
        critic_out = f"[Critic error: {critic_out}]"
    if isinstance(executor_out, Exception):
        executor_out = f"[Executor error: {executor_out}]"

    for line in str(critic_out).split("\n"):
        yield {"architect_agent": "critic", "chunk": line + "\n", "done": False}
        await asyncio.sleep(0.004)
    yield {"architect_agent": "critic", "chunk": "", "done": True}

    yield {"architect_agent": "executor", "chunk": "\n\n### ⚙️ Executor is assessing feasibility and sketching code…\n\n", "done": False}
    for line in str(executor_out).split("\n"):
        yield {"architect_agent": "executor", "chunk": line + "\n", "done": False}
        await asyncio.sleep(0.004)
    yield {"architect_agent": "executor", "chunk": "", "done": True}

    # ── Final: Supervisor streams live synthesis ──────────────────────────────
    full_debate = (
        f"=== RESEARCHER ===\n{researcher_out}\n\n"
        f"=== CREATOR ===\n{creator_out}\n\n"
        f"=== CRITIC ===\n{critic_out}\n\n"
        f"=== EXECUTOR ===\n{executor_out}"
    )

    yield {"architect_agent": "supervisor", "chunk": "\n\n---\n\n### 🧠 Supervisor is synthesising the debate into a final proposal…\n\n", "done": False}

    sup_msgs = [
        {"role": "system", "content": _supervisor_prompt(owner)},
        {"role": "system", "content": f"Full team debate:\n\n{full_debate}"},
        {"role": "user", "content": user_prompt},
    ]

    proposal_parts: list[str] = []
    try:
        async for tok in stream_tokens(sup_msgs, use_deep=True, max_tokens=2000, temperature=0.35):
            proposal_parts.append(tok)
            yield {"architect_agent": "supervisor", "chunk": tok, "done": False}
    except Exception as e:
        err = f"\n[Supervisor stream error: {e}]"
        proposal_parts.append(err)
        yield {"architect_agent": "supervisor", "chunk": err, "done": False}

    yield {"architect_agent": "supervisor", "chunk": "", "done": True}

    final_proposal = "".join(proposal_parts)
    latency = int((time.monotonic() - t0) * 1000)

    # Store in Redis for background notifications
    try:
        from utils.redis_client import get_redis
        redis = get_redis()
        payload = json.dumps({
            "proposal": final_proposal,
            "debate": {
                "researcher": str(researcher_out),
                "creator": str(creator_out),
                "critic": str(critic_out),
                "executor": str(executor_out),
            },
            "latency_ms": latency,
            "timestamp": time.time(),
        })
        await redis.setex("architect:latest_proposal", 86400 * 3, payload)  # 3-day TTL
        logger.info("Architect proposal saved to Redis")
    except Exception as e:
        logger.warning(f"Could not save architect proposal to Redis: {e}")

    yield {
        "architect_done": True,
        "proposal": final_proposal,
        "latency_ms": latency,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Background 24/7 cycle (called by APScheduler every 12 hours)
# ─────────────────────────────────────────────────────────────────────────────

async def run_background_architect_cycle() -> None:
    """
    Background evolution cycle — runs every 12 hours via APScheduler.
    Generates a new proposal, stores it in Redis, and sends a notification.
    Does NOT auto-implement anything — waits for explicit user approval.
    """
    logger.info("Architect background cycle starting…")
    try:
        # Collect all events (not streaming to a client here)
        proposal_text = ""
        async for event in stream_architect_proposal(
            query=(
                "Background cycle: analyse IRA's current capabilities and propose "
                "the single most impactful feature to add next based on what Grok, "
                "Claude, Gemini, and ChatGPT released in the last cycle."
            ),
            background_mode=True,
        ):
            if event.get("architect_done"):
                proposal_text = event.get("proposal", "")

        if not proposal_text:
            logger.warning("Architect background cycle produced no proposal")
            return

        # Send notification so the user knows there is something new
        cfg = get_settings()
        # Fix #80: "Architect Cycle" title was too cryptic — the user needs to
        # understand at a glance that there is an actionable proposal waiting.
        notification_msg = (
            f"🏛️ *IRA Evolution Team — New Feature Proposal Ready, {cfg.owner_name}!*\n\n"
            "Your 5-agent engineering team completed their 12-hour analysis cycle "
            "and has a feature proposal ready for your review.\n\n"
            "Type **`architect propose`** in the IRA chat to see the full debate and proposal.\n\n"
            "_Nothing has been implemented — awaiting your approval._"
        )

        try:
            from worker.notifier import notify
            await notify(
                title="IRA Evolution Team — New Proposal Ready",
                body=notification_msg,
                category="system",
                priority="info",
            )
            logger.info("Architect proposal notification sent")
        except Exception as e:
            logger.warning(f"Architect notification failed (non-critical): {e}")

        logger.info("Architect background cycle completed successfully")

    except Exception as e:
        logger.error(f"Architect background cycle failed: {e}", exc_info=True)


# ─────────────────────────────────────────────────────────────────────────────
# Auto-implementation (after explicit user approval)
# ─────────────────────────────────────────────────────────────────────────────

_IMPL_SYSTEM = """\
You are the IRA Auto-Implementation Engine.

When given a feature to implement, output the COMPLETE implementation as unified diffs.
Every change must be immediately applicable with `git apply`.
Use real file paths relative to the supracloud-jarvis/ root.

Output format:
## Implementation: [Feature Name]

### Summary
[2-sentence description of what was implemented]

### Files Changed
- `path/to/file` — reason

### Diffs
```diff
--- a/ira/path/to/file.py
+++ b/ira/path/to/file.py
@@ -N,M +N,M @@
 context
-removed
+added
 context
```

### New Requirements (if any)
```
package>=version
```

### Restart Command
```bash
docker compose restart ira-api
```

### Git Commit
```
feat: [feature] — [description]
```

Rules:
- Never rewrite files entirely — only surgical diffs
- Include 3 lines of context around each hunk
- New files use --- /dev/null and +++ b/path
- Keep every diff minimal and correct
"""

_IRA_CONTEXT = """\
IRA Stack (supracloud-jarvis/):
  ira/agents/          — LangGraph agents (expert_mode.py, engineer_agent.py, architect_agent.py)
  ira/api/routes/      — FastAPI routes (chat.py, image_gen.py, video_gen.py, document_create.py)
  ira/utils/           — helpers (llm.py, search_tools.py, auto_implement.py)
  ira/worker/          — background jobs (scheduler.py, briefing.py, self_healing.py)
  ira/config.py        — pydantic-settings
  ira/main.py          — FastAPI app factory
  ira/requirements.txt — Python dependencies
  frontend/components/ — ChatInterface.tsx, Sidebar.tsx
  frontend/app/        — page.tsx
"""


async def stream_auto_implement(
    feature_name: str,
    proposal_context: str = "",
) -> AsyncIterator[dict]:
    """Stream the auto-implementation code generation for an approved feature."""
    cfg = get_settings()

    yield {
        "implement_start": True,
        "message": f"⚙️ **Implementing: {feature_name}**\n\nGenerating code, diffs, and commit message…\n\n",
    }

    msgs = [
        {"role": "system", "content": _IMPL_SYSTEM},
        {"role": "system", "content": _IRA_CONTEXT},
        {
            "role": "user",
            "content": (
                f"Implement **{feature_name}** for {cfg.owner_name}'s IRA system.\n\n"
                f"Context from proposal:\n{proposal_context[:4000]}"
            ),
        },
    ]

    parts: list[str] = []
    try:
        async for tok in stream_tokens(msgs, use_deep=True, max_tokens=4096, temperature=0.15):
            parts.append(tok)
            yield {"implement_chunk": tok}
    except Exception as e:
        err = f"\n\n[Implementation error: {e}]"
        parts.append(err)
        yield {"implement_chunk": err}

    impl_text = "".join(parts)

    yield {
        "implement_done": True,
        "implementation": impl_text,
        "feature_name": feature_name,
        "message": (
            "\n\n---\n✅ **Implementation generated.**\n\n"
            "Review the diffs above, then:\n"
            "- **Apply now:** type `architect apply`\n"
            "- **Dry-run first:** type `architect dry run`\n"
            "- **Cancel:** type `architect cancel`"
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Trigger detection helpers
# ─────────────────────────────────────────────────────────────────────────────

_PROPOSAL_RE = re.compile(
    r"\b(architect|propose( new)? features?|evolution team|"
    r"what should (we|ira) build|new feature ideas?|ira evolve|"
    r"improve ira|what'?s? (next|missing)|architect (next )?proposal)\b",
    re.I,
)
_IMPLEMENT_RE = re.compile(
    r"\b(architect implement|implement (this|feature|it|that)|"
    r"go ahead (with|and build)|^approve$|approved|build (this|it|feature)|"
    r"yes,? (do it|implement|build it|go ahead))\b",
    re.I,
)
_APPLY_RE = re.compile(r"^architect\s+apply$", re.IGNORECASE)
_SHOW_CODE_RE = re.compile(
    r"\b(architect show code|show (me )?(the )?(code|diff|implementation)|"
    r"show implementation)\b",
    re.I,
)


def is_architect_trigger(q: str) -> bool:
    return bool(_PROPOSAL_RE.search(q))

def is_implement_trigger(q: str) -> bool:
    return bool(_IMPLEMENT_RE.search(q))

def is_apply_trigger(q: str) -> bool:
    return bool(_APPLY_RE.search(q))

def is_show_code_trigger(q: str) -> bool:
    return bool(_SHOW_CODE_RE.search(q))


def extract_feature_name(q: str) -> str:
    m = re.search(
        r"(?:architect implement|implement|go ahead with|build|approve)[:\s]+(.+)",
        q, re.I,
    )
    return (m.group(1).strip() if m else "the top recommended feature")
