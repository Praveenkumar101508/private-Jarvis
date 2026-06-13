"""
IRA — Strategy Mode: bounded LLM deliberation (the *buildable* version of the
"LLM + search" idea).

WHAT THIS IS — AND ISN'T
  This is NOT Stockfish. There is no exact world model, no objective reward, and
  no cheap exhaustive rollouts, so we cannot search to a provably-optimal move.
  Errors compound with depth, so we deliberately keep lookahead SHALLOW.
  What this DOES is the productive core that actually helps: the LLM acts as both
  the *policy* (proposes only a few promising options) and the *value function*
  (scores/prunes them), with 1-step (optionally 2-step) lookahead. The output is
  decision SUPPORT — surfaced scenarios, scores, assumptions, and the main risks —
  not an oracle verdict. Every projected outcome is labelled ESTIMATED.

  This is the same family as Tree-of-Thoughts / LATS / RAP and what reasoning
  models do internally — just made explicit, sovereign (local Ollama), and bounded.

WHERE IT FITS IRA
  A natural extension of the 5-agent council (agents/expert_mode.py). Opt-in and
  routed: `is_strategy_request()` only fires on explicit strategic asks, and it is
  kept OFF the voice/quick-chat path (it's slower — several LLM calls).

EFFICIENCY KNOBS (env; the answer to "how do you keep the search space small"):
  STRATEGY_BRANCHES            K candidate options                  (default 4)
  STRATEGY_DEPTH               lookahead depth, hard-capped at 2    (default 1)
  STRATEGY_SELF_CONSISTENCY    sample scoring N× and average        (default 1)
  STRATEGY_DEEP_SYNTHESIS      use the 14B for frame + final pick   (default true)
The two biggest levers are BRANCHES (policy prunes up front) and DEPTH (kept
shallow on purpose). Rollouts/scoring run on the fast 8B; framing + final
synthesis use the deep 14B.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field

from utils.llm import chat_complete

logger = logging.getLogger("ira.strategy")

# ── Bounds (kept small on purpose — see module docstring) ─────────────────────
_MAX_DEPTH = 2  # hard ceiling: deeper lookahead compounds LLM error, hurting quality


@dataclass
class StrategyConfig:
    branches: int = int(os.getenv("STRATEGY_BRANCHES", "4"))
    depth: int = min(int(os.getenv("STRATEGY_DEPTH", "1")), _MAX_DEPTH)
    self_consistency: int = max(int(os.getenv("STRATEGY_SELF_CONSISTENCY", "1")), 1)
    deep_synthesis: bool = os.getenv("STRATEGY_DEEP_SYNTHESIS", "true").lower() in ("1", "true", "yes", "on")


@dataclass
class Option:
    name: str
    description: str
    projected_outcome: str = ""          # ESTIMATED — the LLM's imagined consequence
    assumptions: list[str] = field(default_factory=list)
    success_probability: float = 0.0     # 0..1  (estimated)
    risk: float = 0.0                    # 0..1  (estimated downside likelihood/severity)
    effort: float = 0.0                  # 0..1  (estimated cost/effort)
    confidence: float = 0.0              # 0..1  how much to trust this estimate
    main_risk: str = ""
    utility: float = 0.0                 # composite score used for ranking


@dataclass
class StrategyResult:
    question: str
    objective: str
    criteria: list[str]
    options: list[Option]                # ranked, best first
    recommended: str
    rationale: str
    runner_up: str
    what_would_change_it: str
    note: str = (
        "Decision support, not a guarantee. Outcomes are the model's estimates "
        "(bounded by its world model), not ground-truth simulation."
    )

    def to_spoken_summary(self) -> str:
        """Short, for voice — one or two sentences."""
        top = self.options[0] if self.options else None
        if not top:
            return "I couldn't work out clear options for that — can you add a bit more detail?"
        pct = int(round(top.success_probability * 100))
        return (
            f"My pick is {self.recommended}. {self.rationale} "
            f"Roughly {pct}% odds as I see it, main risk: {top.main_risk}. "
            f"Want the full breakdown?"
        )

    def to_markdown(self) -> str:
        lines = [f"**Decision:** {self.question}", f"**Objective:** {self.objective}", ""]
        if self.criteria:
            lines.append("**Judging by:** " + ", ".join(self.criteria))
            lines.append("")
        lines.append(f"**Recommendation: {self.recommended}**")
        lines.append(f"{self.rationale}")
        lines.append(f"_Runner-up:_ {self.runner_up}")
        lines.append(f"_What would change this:_ {self.what_would_change_it}")
        lines.append("")
        lines.append("**Options considered (estimated):**")
        for i, o in enumerate(self.options, 1):
            lines.append(
                f"{i}. **{o.name}** — score {o.utility:.2f} "
                f"(success ~{int(o.success_probability*100)}%, risk {o.risk:.2f}, "
                f"effort {o.effort:.2f}, confidence {o.confidence:.2f})"
            )
            lines.append(f"   - Likely outcome (estimated): {o.projected_outcome}")
            if o.assumptions:
                lines.append("   - Assumes: " + "; ".join(o.assumptions))
            if o.main_risk:
                lines.append(f"   - Main risk: {o.main_risk}")
        lines.append("")
        lines.append(f"> {self.note}")
        return "\n".join(lines)


# ── Robust JSON extraction (qwen3 may emit <think>…</think> and/or ``` fences) ─
def _extract_json(text: str):
    if not text:
        return None
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)   # strip thinking
    text = re.sub(r"```(?:json)?|```", "", text)                       # strip fences
    # Grab the first balanced {...} or [...] block.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(text)):
            if text[i] == opener:
                depth += 1
            elif text[i] == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    return None


async def _ask_json(system: str, user: str, *, use_deep: bool, temperature: float):
    """One LLM call that must return JSON. Returns parsed JSON or None."""
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    try:
        raw = await chat_complete(msgs, use_deep=use_deep, temperature=temperature, max_tokens=900)
    except Exception as e:
        logger.error(f"strategy LLM call failed: {e}")
        return None
    return _extract_json(raw if isinstance(raw, str) else "")


def _clamp01(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, v))


# ── Pipeline steps ────────────────────────────────────────────────────────────
async def _frame(question: str, context: str, cfg: StrategyConfig) -> dict:
    sys = (
        "You frame a decision precisely. Return ONLY JSON: "
        '{"objective": str, "criteria": [str], "constraints": [str], "unknowns": [str]}. '
        "criteria = what makes an answer good here. Be concrete and short."
    )
    usr = f"DECISION:\n{question}\n\nCONTEXT:\n{context or '(none)'}"
    data = await _ask_json(sys, usr, use_deep=cfg.deep_synthesis, temperature=0.2) or {}
    return {
        "objective": str(data.get("objective", question))[:400],
        "criteria": [str(c) for c in data.get("criteria", [])][:6],
        "constraints": [str(c) for c in data.get("constraints", [])][:6],
        "unknowns": [str(c) for c in data.get("unknowns", [])][:6],
    }


async def _generate_options(frame: dict, question: str, cfg: StrategyConfig) -> list[Option]:
    sys = (
        f"Propose exactly {cfg.branches} GENUINELY DIFFERENT strategies (not variations of one). "
        'Return ONLY JSON: {"options": [{"name": str, "description": str}]}. '
        "Each name ≤ 6 words; description ≤ 2 sentences."
    )
    usr = (
        f"DECISION: {question}\nOBJECTIVE: {frame['objective']}\n"
        f"CONSTRAINTS: {frame['constraints']}\nCRITERIA: {frame['criteria']}"
    )
    data = await _ask_json(sys, usr, use_deep=cfg.deep_synthesis, temperature=0.7) or {}
    opts = [
        Option(name=str(o.get("name", f"Option {i+1}"))[:80], description=str(o.get("description", ""))[:400])
        for i, o in enumerate(data.get("options", []))
    ]
    return opts[: cfg.branches]


async def _lookahead_and_score(opt: Option, frame: dict, cfg: StrategyConfig) -> Option:
    """Shallow imagined rollout + scoring. Fast tier. Self-consistency optional."""
    depth_hint = (
        "Imagine the single most likely consequence."
        if cfg.depth <= 1
        else "Imagine the most likely consequence, then one realistic counter-reaction, then your follow-up."
    )
    sys = (
        "You forecast and score ONE strategy. All outcomes are ESTIMATES. "
        f"{depth_hint} Return ONLY JSON: "
        '{"projected_outcome": str, "assumptions": [str], "success_probability": 0..1, '
        '"risk": 0..1, "effort": 0..1, "confidence": 0..1, "main_risk": str}.'
    )
    usr = (
        f"OBJECTIVE: {frame['objective']}\nCRITERIA: {frame['criteria']}\n"
        f"STRATEGY: {opt.name} — {opt.description}\nKNOWN UNKNOWNS: {frame['unknowns']}"
    )
    samples = []
    for _ in range(cfg.self_consistency):
        d = await _ask_json(sys, usr, use_deep=False, temperature=0.3)
        if d:
            samples.append(d)
    if not samples:
        opt.confidence = 0.0
        opt.main_risk = "Could not estimate (model returned no usable forecast)."
        return opt

    def avg(key):
        vals = [_clamp01(s.get(key)) for s in samples]
        return sum(vals) / len(vals)

    first = samples[0]
    opt.projected_outcome = str(first.get("projected_outcome", ""))[:500]
    opt.assumptions = [str(a) for a in first.get("assumptions", [])][:5]
    opt.main_risk = str(first.get("main_risk", ""))[:300]
    opt.success_probability = avg("success_probability")
    opt.risk = avg("risk")
    opt.effort = avg("effort")
    opt.confidence = avg("confidence")
    # Composite utility: reward success, penalise risk + effort, weight by confidence.
    raw = opt.success_probability - 0.6 * opt.risk - 0.25 * opt.effort
    opt.utility = round(((raw + 1) / 2) * (0.5 + 0.5 * opt.confidence), 4)  # → 0..1
    return opt


async def _synthesise(frame: dict, question: str, ranked: list[Option], cfg: StrategyConfig) -> dict:
    top = ranked[: min(2, len(ranked))]
    sys = (
        "Pick the best strategy from the finalists and explain briefly. "
        'Return ONLY JSON: {"recommended": str, "rationale": str, "runner_up": str, '
        '"what_would_change_it": str}. rationale ≤ 2 sentences.'
    )
    usr = "OBJECTIVE: " + frame["objective"] + "\nFINALISTS:\n" + "\n".join(
        f"- {o.name}: outcome={o.projected_outcome} | success~{o.success_probability:.2f} "
        f"risk={o.risk:.2f} effort={o.effort:.2f} conf={o.confidence:.2f} | risk: {o.main_risk}"
        for o in top
    )
    data = await _ask_json(sys, usr, use_deep=cfg.deep_synthesis, temperature=0.2) or {}
    best = ranked[0]
    return {
        "recommended": str(data.get("recommended", best.name))[:120],
        "rationale": str(data.get("rationale", best.projected_outcome))[:500],
        "runner_up": str(data.get("runner_up", ranked[1].name if len(ranked) > 1 else "—"))[:120],
        "what_would_change_it": str(data.get("what_would_change_it", "New information about the key unknowns."))[:400],
    }


# ── Public API ────────────────────────────────────────────────────────────────
_STRATEGY_TRIGGERS = re.compile(
    r"\b(should i|should we|decide between|which.*better|best (option|strategy|move|approach)|"
    r"strateg|negotiat|trade[- ]?off|pros and cons|what.*do (about|with)|go to market|"
    r"compete|prioriti[sz]e)\b",
    re.IGNORECASE,
)


def is_strategy_request(query: str) -> bool:
    """Conservative detector. Strategy mode is opt-in and kept OFF voice/quick chat
    by the caller; this only fires on explicit strategic/decision asks."""
    return bool(query and _STRATEGY_TRIGGERS.search(query))


async def run_strategy(question: str, *, context: str = "", config: StrategyConfig | None = None) -> StrategyResult:
    """Run the bounded deliberation pipeline. Several LLM calls — not for the
    low-latency voice path. Degrades gracefully if the model returns junk."""
    cfg = config or StrategyConfig()
    logger.info(f"strategy: branches={cfg.branches} depth={cfg.depth} sc={cfg.self_consistency}")

    frame = await _frame(question, context, cfg)
    options = await _generate_options(frame, question, cfg)
    if not options:
        return StrategyResult(
            question=question, objective=frame["objective"], criteria=frame["criteria"],
            options=[], recommended="—",
            rationale="I couldn't generate distinct options — try giving more detail or constraints.",
            runner_up="—", what_would_change_it="—",
        )

    # Score all options in parallel (each is one or a few fast-tier calls).
    options = list(await asyncio.gather(*[_lookahead_and_score(o, frame, cfg) for o in options]))
    options.sort(key=lambda o: o.utility, reverse=True)

    syn = await _synthesise(frame, question, options, cfg)
    return StrategyResult(
        question=question, objective=frame["objective"], criteria=frame["criteria"],
        options=options, recommended=syn["recommended"], rationale=syn["rationale"],
        runner_up=syn["runner_up"], what_would_change_it=syn["what_would_change_it"],
    )


# ── Standalone smoke test (run on the Shadow box with Ollama up) ──────────────
# Usage:  python -m agents.strategy_mode "Should I take the Dubai role or grow SupraCloud?"
if __name__ == "__main__":  # pragma: no cover
    import sys
    logging.basicConfig(level=logging.INFO)
    q = sys.argv[1] if len(sys.argv) > 1 else "Should I take the Dubai role or stay and grow SupraCloud?"
    res = asyncio.run(run_strategy(q))
    print("\n" + res.to_markdown())
    print("\nSPOKEN:", res.to_spoken_summary())
