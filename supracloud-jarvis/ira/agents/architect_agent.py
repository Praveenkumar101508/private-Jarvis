"""
IRA Architect / Evolution Agent — Self-Evolving Engineering Team.

A permanent team of 5 specialist agents that debates new features, compares
IRA against Grok / Claude / Gemini / ChatGPT / DeepSeek, invents unique ideas,
and auto-implements approved features with full git workflow.

Team structure:
  Researcher → maps IRA capability gaps vs other AIs, gathers context
  Critic     → argues against (risk, complexity, maintenance burden)
  Executor   → assesses technical feasibility + writes implementation code
  Creator    → invents unique features no other AI has yet
  Supervisor → synthesises debate → polished proposal + ranked recommendations

Activation: user says "architect", "propose new features", "evolution team"
Approval:   user says "Approve", "Implement", "Go ahead with [feature]"
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncIterator

from config import get_settings
from utils.llm import chat_complete, stream_tokens

logger = logging.getLogger("ira.architect")

# ─────────────────────────────────────────────────────────────────────────────
# Feature Gap Database — what the major AIs have that IRA lacks (May 2026)
# The Researcher agent references this to generate targeted proposals.
# ─────────────────────────────────────────────────────────────────────────────
FEATURE_GAP_DATABASE = """
## VERIFIED FEATURE GAPS (IRA vs Leading AIs — May 2026)

### Already at PARITY or SUPERIOR:
- Multi-agent Expert Mode (5 parallel agents) ✅
- Real-time X/Twitter search with country awareness ✅
- Web search + DeepSearch (3-round iterative) ✅
- Think Mode / reasoning chains ✅
- Image generation (FLUX via Replicate) ✅
- Image editing (InstructPix2Pix) ✅
- Vision / image analysis ✅
- PDF/DOCX/TXT document upload ✅
- Voice interface (LiveKit + Whisper + Kokoro) ✅
- Engineer Mode (4-step code workflow) ✅
- Grok personality ✅
- Self-healing with git commit ✅
- Persistent memory + RAG ✅
- Biometric voice verification ✅
- Daily backup + restore ✅
- Cloud-ready model config (Qwen3 / DeepSeek R1) ✅

### MISSING (Priority Order):
1. **Video Generation** (text→video, image→video) — Grok Imagine Video, Gemini Veo 3, Kling 2.6
2. **Computer Use / Desktop Agent** — Claude Computer Use, Grok Computer, controlling mouse/keyboard/browser
3. **Native Document Creation** — formatted PDF, PowerPoint, Excel from chat (Claude Artifacts-style)
4. **Video Understanding** — upload and analyse video files (Gemini 1.5 Pro, GPT-4o)
5. **Music / Audio Generation** — full song synthesis, voice cloning (Suno, Udio integrations)
6. **Canvas / Design Mode** — Figma-style UI generation, Canva-like design, slide decks
7. **Code Execution Sandbox** — run Python/JS code live in a sandboxed container (ChatGPT Code Interpreter)
8. **Multi-modal Art Direction** — combine voice + image + text into creative projects
9. **Persistent Agent Tasks** — background multi-step tasks that run for hours (Devin-style)
10. **Real-time Voice Conversation** — sub-200ms latency voice-to-voice (GPT-4o Realtime API style)

### UNIQUE IDEAS (nobody has these yet):
- **Lifelong Memory Graph** — knowledge graph that connects all memories as a visual graph
- **IRA Dashboard** — real-time Notion-like home screen IRA updates with your projects, tasks, health
- **Silent Background Agent** — continuously monitors your email/GitHub/calendar and quietly acts
- **IRA API Gateway** — expose IRA's capabilities as a public API with rate limits (monetise your AI)
- **Context Compression** — ultra-long conversations compressed without losing facts (10M+ token context)
"""

# ─────────────────────────────────────────────────────────────────────────────
# Agent system prompts
# ─────────────────────────────────────────────────────────────────────────────

def _researcher_prompt(owner: str) -> str:
    return f"""\
You are the RESEARCHER in {owner}'s IRA Architect Team — an AI evolution analyst.

Your job: Analyse the feature gap database below and identify the TOP 3 features \
IRA should add next, ranked by user value + implementation feasibility.

For each feature, provide:
- What Grok/Claude/Gemini/ChatGPT currently offer in this area
- Why {owner}'s specific use case benefits from it
- One unique angle IRA could take that the big AIs don't have

Format exactly:
🔬 RESEARCHER ANALYSIS:
**Feature 1: [Name]** — [Why now, what gap it fills, specific competitor comparison]
**Feature 2: [Name]** — [Why now, what gap it fills, specific competitor comparison]
**Feature 3: [Name]** — [Why now, what gap it fills, specific competitor comparison]
Confidence: HIGH

{FEATURE_GAP_DATABASE}"""


def _critic_prompt(owner: str) -> str:
    return f"""\
You are the CRITIC in {owner}'s IRA Architect Team — the voice of reason and risk.

The Researcher will propose 3 features. Your job: push back hard.
For EACH proposed feature identify:
- Implementation complexity (1-10)
- Maintenance burden
- Risk of breaking existing features
- Whether the effort is worth it for a single-person system
- Cheaper alternatives that achieve 80% of the value

Format exactly:
🛡️ CRITIC REVIEW:
**On [Feature 1]:** [Your challenge + complexity rating + risk + alternative]
**On [Feature 2]:** [Your challenge + complexity rating + risk + alternative]
**On [Feature 3]:** [Your challenge + complexity rating + risk + alternative]
Overall Risk: [PROCEED/CAUTION/REJECT]"""


def _executor_prompt(owner: str) -> str:
    return f"""\
You are the EXECUTOR in {owner}'s IRA Architect Team — the hands-on engineer.

Based on the Researcher's proposals and Critic's concerns, assess:
1. Which feature can be implemented FASTEST with highest impact?
2. Exact implementation plan (files to create/modify, libraries to add)
3. What would the actual code look like? Give a short snippet for each.
4. Estimated hours to implement each feature end-to-end.

The IRA stack: FastAPI + LangGraph + Next.js/TypeScript + PostgreSQL + Redis + vLLM + Docker.

Format exactly:
⚙️ EXECUTOR ASSESSMENT:
**Quick Win (#1 pick):** [Feature name + exact implementation steps + estimated hours]
**Medium Effort (#2):** [Feature name + key files + libraries + estimated hours]
**Major Feature (#3):** [Feature name + high-level architecture + estimated weeks]
Recommendation: [Which one to build first and why]
Feasibility: READY"""


def _creator_prompt(owner: str) -> str:
    return f"""\
You are the CREATOR in {owner}'s IRA Architect Team — the visionary.

Your job: go BEYOND what the Researcher proposed.
Invent 1-2 completely NEW features that:
- No other AI (Grok/Claude/Gemini/ChatGPT) currently offers
- Would give {owner} a genuine superpower in their daily/business life
- Are actually buildable in the IRA stack (FastAPI + Next.js + vLLM)

Think: What does {owner} do every day where AI could silently supercharge them?
Think: What combination of IRA's existing features creates something entirely new?

Format exactly:
✨ CREATOR INVENTION:
**Unique Idea 1: [Feature Name]** — [Concept + how it uses existing IRA strengths + why nobody else has it]
**Unique Idea 2: [Feature Name]** — [Concept + how it uses existing IRA strengths + why nobody else has it]
Innovation Score: BREAKTHROUGH"""


def _supervisor_prompt(owner: str) -> str:
    return f"""\
You are the SUPERVISOR in {owner}'s IRA Architect Team.

You have seen the full debate between Researcher, Critic, Executor, and Creator.
Now produce the FINAL POLISHED PROPOSAL for {owner} to review and approve.

The proposal must include:
1. **Top Recommendation** — single best feature to build next with full justification
2. **Complete Implementation Plan** — exact files, diffs, libraries, docker changes needed
3. **Debate Summary** — what each agent said (3-4 lines each)
4. **Unique Angle** — what makes IRA's version better than Grok/Claude/Gemini's equivalent
5. **Risk & Mitigation** — what could go wrong and how to prevent it
6. **Effort** — realistic hours/days estimate
7. **Two Alternatives** — features #2 and #3 in brief, with implementation sketches

End with EXACTLY this block (user will reply to approve):
---
**To approve:** Reply with **"Architect implement: [feature name]"**
**To see alternatives:** Reply with **"Architect alternatives"**
**To propose something else:** Reply with **"Architect propose [your idea]"**
---"""


# ─────────────────────────────────────────────────────────────────────────────
# Core streaming debate function
# ─────────────────────────────────────────────────────────────────────────────

async def _run_agent(
    agent_name: str,
    system_prompt: str,
    user_content: str,
    context: str = "",
) -> str:
    """Run a single architect agent and return its output."""
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    if context:
        messages.append({"role": "system", "content": f"Team context so far:\n{context}"})
    messages.append({"role": "user", "content": user_content})
    try:
        return await chat_complete(messages, use_deep=True, max_tokens=1200, temperature=0.7)
    except Exception as e:
        logger.error(f"Architect agent {agent_name} failed: {e}")
        return f"[{agent_name} encountered an error: {e}]"


async def stream_architect_proposal(
    query: str,
    memory_context: str = "",
) -> AsyncIterator[dict]:
    """
    Stream the full 5-agent architectural debate as SSE events.

    Yields dicts matching the SSE event format:
      {"architect_agent": "researcher", "chunk": "...", "done": False}
      {"architect_agent": "supervisor",  "chunk": "...", "done": True}
      {"architect_done": True, "proposal": "..."}
    """
    cfg = get_settings()
    owner = cfg.owner_name
    t0 = time.monotonic()

    # Build user prompt for all agents
    user_prompt = (
        f"Analyse IRA's current capabilities and the user's request: '{query}'\n\n"
        f"Memory context:\n{memory_context}" if memory_context
        else f"Analyse IRA's current capabilities and the user's request: '{query}'"
    )

    # ── Phase 1: Yield "debate starting" signal ───────────────────────────────
    yield {
        "architect_start": True,
        "message": "🏛️ IRA Architect Team is convening — internal debate starting…",
    }
    await asyncio.sleep(0.05)

    # ── Phase 2: Researcher + Creator run in parallel (independent) ───────────
    yield {"architect_agent": "researcher", "chunk": "🔬 **Researcher** is analysing feature gaps…\n", "done": False}

    researcher_task = asyncio.create_task(
        _run_agent("researcher", _researcher_prompt(owner), user_prompt)
    )
    creator_task = asyncio.create_task(
        _run_agent("creator", _creator_prompt(owner), user_prompt)
    )

    researcher_output, creator_output = await asyncio.gather(
        researcher_task, creator_task, return_exceptions=True
    )
    if isinstance(researcher_output, Exception):
        researcher_output = f"[Researcher error: {researcher_output}]"
    if isinstance(creator_output, Exception):
        creator_output = f"[Creator error: {creator_output}]"

    # Stream researcher output token by token (simulate)
    for line in researcher_output.split("\n"):
        yield {"architect_agent": "researcher", "chunk": line + "\n", "done": False}
        await asyncio.sleep(0.005)

    yield {"architect_agent": "researcher", "chunk": "", "done": True}

    # ── Phase 3: Critic + Executor run in parallel (they have researcher context) ─
    context_so_far = f"RESEARCHER:\n{researcher_output}\n\nCREATOR:\n{creator_output}"

    yield {"architect_agent": "critic", "chunk": "🛡️ **Critic** is reviewing the proposals…\n", "done": False}

    critic_task = asyncio.create_task(
        _run_agent("critic", _critic_prompt(owner), user_prompt, context=context_so_far)
    )
    executor_task = asyncio.create_task(
        _run_agent("executor", _executor_prompt(owner), user_prompt, context=context_so_far)
    )

    critic_output, executor_output = await asyncio.gather(
        critic_task, executor_task, return_exceptions=True
    )
    if isinstance(critic_output, Exception):
        critic_output = f"[Critic error: {critic_output}]"
    if isinstance(executor_output, Exception):
        executor_output = f"[Executor error: {executor_output}]"

    for line in critic_output.split("\n"):
        yield {"architect_agent": "critic", "chunk": line + "\n", "done": False}
        await asyncio.sleep(0.005)
    yield {"architect_agent": "critic", "chunk": "", "done": True}

    yield {"architect_agent": "executor", "chunk": "⚙️ **Executor** is assessing feasibility…\n", "done": False}
    for line in executor_output.split("\n"):
        yield {"architect_agent": "executor", "chunk": line + "\n", "done": False}
        await asyncio.sleep(0.005)
    yield {"architect_agent": "executor", "chunk": "", "done": True}

    # Stream creator output
    yield {"architect_agent": "creator", "chunk": "✨ **Creator** has new ideas…\n", "done": False}
    for line in creator_output.split("\n"):
        yield {"architect_agent": "creator", "chunk": line + "\n", "done": False}
        await asyncio.sleep(0.005)
    yield {"architect_agent": "creator", "chunk": "", "done": True}

    # ── Phase 4: Supervisor synthesises everything ────────────────────────────
    full_debate = (
        f"RESEARCHER OUTPUT:\n{researcher_output}\n\n"
        f"CREATOR OUTPUT:\n{creator_output}\n\n"
        f"CRITIC OUTPUT:\n{critic_output}\n\n"
        f"EXECUTOR OUTPUT:\n{executor_output}"
    )

    yield {"architect_agent": "supervisor", "chunk": "🧠 **Supervisor** is synthesising the debate into a final proposal…\n", "done": False}

    # Stream supervisor output live
    supervisor_messages = [
        {"role": "system", "content": _supervisor_prompt(owner)},
        {"role": "system", "content": f"Full team debate:\n\n{full_debate}"},
        {"role": "user", "content": user_prompt},
    ]

    full_proposal_parts: list[str] = []
    try:
        async for token in stream_tokens(supervisor_messages, use_deep=True, max_tokens=2000, temperature=0.4):
            full_proposal_parts.append(token)
            yield {"architect_agent": "supervisor", "chunk": token, "done": False}
    except Exception as e:
        err_msg = f"\n\n[Supervisor error: {e}]"
        full_proposal_parts.append(err_msg)
        yield {"architect_agent": "supervisor", "chunk": err_msg, "done": False}

    yield {"architect_agent": "supervisor", "chunk": "", "done": True}

    latency = int((time.monotonic() - t0) * 1000)
    full_proposal = "".join(full_proposal_parts)

    yield {
        "architect_done": True,
        "proposal": full_proposal,
        "latency_ms": latency,
        "debate": {
            "researcher": researcher_output,
            "creator": creator_output,
            "critic": critic_output,
            "executor": executor_output,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Auto-implementation (called when user approves a feature)
# ─────────────────────────────────────────────────────────────────────────────

_IMPLEMENT_SYSTEM = """\
You are the IRA Auto-Implementation Engine — the Executor in action.

When asked to implement a feature, you:
1. Output a complete implementation as unified diffs (--- a/path +++ b/path format)
2. Include EVERY file that needs to change (backend + frontend + config)
3. Add clear one-sentence comments on each hunk explaining the change
4. Output a `docker compose restart` command for only the affected services
5. Output a git commit message following conventional commits format

IMPORTANT:
- The IRA stack: FastAPI (ira/) + Next.js (frontend/) + Docker
- Use relative paths from the supracloud-jarvis/ directory
- Every diff must be immediately applicable with `git apply`
- Keep changes minimal and surgical — do not rewrite working code
- Output in this exact structure:

## Implementation: [Feature Name]

### Files Changed
- `path/to/file.py` — one-sentence reason

### Diffs
```diff
--- a/ira/...
+++ b/ira/...
@@ ... @@
...
```

### Restart Command
```bash
docker compose restart ira-api
```

### Git Commit Message
```
feat: [feature name] — [one line description]
```
"""


async def stream_auto_implement(
    feature_name: str,
    proposal_context: str,
    memory_context: str = "",
) -> AsyncIterator[dict]:
    """
    Stream the auto-implementation of an approved feature.
    Yields SSE events with implementation progress, then the actual diffs.
    """
    cfg = get_settings()
    owner = cfg.owner_name

    yield {
        "implement_start": True,
        "message": f"⚙️ Auto-implementing: **{feature_name}** — generating code…",
    }

    messages = [
        {"role": "system", "content": _IMPLEMENT_SYSTEM},
        {"role": "system", "content": f"IRA Stack context:\n{_IRA_STACK_CONTEXT}"},
        {
            "role": "user",
            "content": (
                f"Implement this feature for {owner}'s IRA system:\n"
                f"**Feature:** {feature_name}\n\n"
                f"**Context from proposal:**\n{proposal_context[:3000]}"
            ),
        },
    ]

    impl_parts: list[str] = []
    try:
        async for token in stream_tokens(messages, use_deep=True, max_tokens=4096, temperature=0.2):
            impl_parts.append(token)
            yield {"implement_chunk": token}
    except Exception as e:
        err = f"\n\n[Implementation error: {e}]"
        impl_parts.append(err)
        yield {"implement_chunk": err}

    full_impl = "".join(impl_parts)

    yield {
        "implement_done": True,
        "implementation": full_impl,
        "feature_name": feature_name,
        "message": (
            "✅ Implementation generated.\n\n"
            "**To apply these changes:** Reply with **'Architect apply'** and I will:\n"
            "1. Run `git apply --check` to validate\n"
            "2. Apply the diffs\n"
            "3. Commit with the message above\n"
            "4. Restart the affected services\n\n"
            "**To review first:** Read the diffs above carefully before approving."
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Trigger detection
# ─────────────────────────────────────────────────────────────────────────────

import re as _re

_PROPOSAL_RE = _re.compile(
    r"\b(architect|propose new features?|evolution team|feature proposal|"
    r"what should we build|new feature ideas?|ira evolve|improve ira)\b",
    _re.I,
)

_IMPLEMENT_RE = _re.compile(
    r"\b(architect implement|implement (this|feature|it|that)|"
    r"go ahead (with|and build)|approve|approved|build (this|it|feature))\b",
    _re.I,
)

_APPLY_RE = _re.compile(
    r"\b(architect apply|apply (the )?(diff|changes|patch)|apply (it|them))\b",
    _re.I,
)


def is_architect_trigger(query: str) -> bool:
    """Return True if the query should activate the Architect Team proposal mode."""
    return bool(_PROPOSAL_RE.search(query))


def is_implement_trigger(query: str) -> bool:
    """Return True if the query is approving a feature for implementation."""
    return bool(_IMPLEMENT_RE.search(query))


def is_apply_trigger(query: str) -> bool:
    """Return True if the user wants to apply the generated diffs."""
    return bool(_APPLY_RE.search(query))


def extract_feature_name(query: str) -> str:
    """Extract the feature name from an implement command, if present."""
    m = _re.search(
        r"architect implement[:\s]+(.+)|implement[:\s]+(.+)|go ahead with[:\s]+(.+)",
        query,
        _re.I,
    )
    if m:
        return (m.group(1) or m.group(2) or m.group(3) or "").strip()
    return "the proposed feature"


# ─────────────────────────────────────────────────────────────────────────────
# IRA stack context (baked in for Executor's implementation accuracy)
# ─────────────────────────────────────────────────────────────────────────────

_IRA_STACK_CONTEXT = """\
SupraCloud IRA stack:
supracloud-jarvis/
  ira/                         ← FastAPI backend (Python 3.12)
    agents/                    ← LangGraph + custom agents
      architect_agent.py       ← This file (Architect Team)
      expert_mode.py           ← 5-agent Expert Mode
      engineer_agent.py        ← Engineer Mode (4-step)
      grok_personality.py      ← Grok system prompt
      graph.py                 ← Agent routing graph
      supervisor.py            ← Query classifier
    api/routes/
      chat.py                  ← /chat/stream (SSE), /chat/expert, /chat/vision
      architect.py             ← /architect/propose, /architect/implement
      image_gen.py             ← /image/generate, /image/edit
    utils/
      llm.py                   ← vLLM 3-tier routing (fast/deep/reasoning)
      search_tools.py          ← Web + X search + DeepSearch
      auto_implement.py        ← git apply + commit + service restart
    config.py                  ← pydantic-settings (env vars)
    main.py                    ← FastAPI app factory + router registration
    requirements.txt
  frontend/                    ← Next.js 14 (TypeScript)
    components/
      ChatInterface.tsx        ← Main chat UI (SSE client) — most complex file
      Sidebar.tsx              ← Mode switcher
    app/
      page.tsx                 ← Auth + layout
  docker-compose.yml           ← Base compose (Shadow PC)
  docker-compose.cloud.yml     ← Cloud overlay (8×H100)
  .env.example                 ← All env var docs
"""
