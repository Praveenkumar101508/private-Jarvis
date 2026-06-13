"""
agents/strategy_mode.py — bounded strategic deliberation (honest, ranked options).

For a strategic question IRA proposes a few distinct options, scores each
(success / risk / effort -> a deterministic utility), ranks them, and is HONEST about
its assumptions, confidence, and what would change the answer.

Bounded by design (Principle: bounded > unbounded): a small branch count, shallow
lookahead (depth ceiling 2), optional self-consistency. This is estimation + ranking
— NOT ground-truth simulation and NOT "optimal." Phase 6 calibrates the success
estimates against the owner's own recorded outcomes.

Knobs in config.py (STRATEGY_*): branches, depth (<=2), self_consistency, deep_synthesis.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from utils.llm import chat_complete

logger = logging.getLogger("ira.strategy")

# Detector — strategic asks only (kept off the low-latency voice fast path).
_STRATEGY_RE = re.compile(
    r"\b(should i|should we|what.?s the best (?:way|strategy|approach|option|move)|"
    r"how (?:should|do) (?:i|we) (?:approach|decide|choose|prioriti[sz]e)|"
    r"pros and cons|trade.?offs?|decide between|choose between|is it worth|"
    r"what are my options|best strategy|strategi[sz]e|weigh (?:the )?options)\b",
    re.I,
)

_SYS = (
    "You are a sharp, honest strategic advisor. You weigh options without inflating "
    "your certainty. You state assumptions plainly and admit what you don't know."
)


def is_strategy_request(query: str) -> bool:
    """True for strategic decision asks (explicit invocation of strategy mode)."""
    return bool(query and _STRATEGY_RE.search(query))


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class StrategyOption:
    name: str
    rationale: str
    success_probability: float
    risk: float
    effort: float
    utility: float = 0.0


@dataclass
class StrategyResult:
    question: str
    options: list[StrategyOption] = field(default_factory=list)   # ranked, best first
    assumptions: list[str] = field(default_factory=list)
    confidence: float = 0.0
    what_would_change_it: list[str] = field(default_factory=list)
    calibrated_on: int = 0       # Phase 6 fills this from recorded outcomes
    degraded: bool = False       # True when the model output couldn't be parsed

    def best(self) -> StrategyOption | None:
        return self.options[0] if self.options else None

    def to_markdown(self) -> str:
        if self.degraded or not self.options:
            return (f"**Strategy:** {self.question}\n\n"
                    "I couldn't produce a confident analysis for this. "
                    "Try rephrasing the decision, or give me the options to weigh.")
        cal = f" · calibrated on {self.calibrated_on} past decision(s)" if self.calibrated_on else ""
        lines = [
            f"## Strategy: {self.question}",
            "",
            f"**Confidence:** {self.confidence:.0%}{cal}",
            "",
            "| Rank | Option | Success | Risk | Effort | Utility |",
            "|---:|---|---:|---:|---:|---:|",
        ]
        for i, o in enumerate(self.options, 1):
            lines.append(
                f"| {i} | {o.name} | {o.success_probability:.0%} | {o.risk:.0%} "
                f"| {o.effort:.0%} | {o.utility:.2f} |"
            )
        best = self.best()
        lines += ["", f"**Top pick — {best.name}:** {best.rationale}"]
        if self.assumptions:
            lines += ["", "**Assumptions:**"] + [f"- {a}" for a in self.assumptions]
        if self.what_would_change_it:
            lines += ["", "**What would change this:**"] + [f"- {w}" for w in self.what_would_change_it]
        return "\n".join(lines)

    def to_spoken_summary(self) -> str:
        if self.degraded or not self.options:
            return "I couldn't analyse that confidently — try giving me the options to weigh."
        best = self.best()
        parts = [f"My pick is {best.name}, about {best.success_probability:.0%} likely to work."]
        if best.rationale:
            parts.append(best.rationale.rstrip("."). strip() + ".")
        if self.assumptions:
            parts.append(f"Key assumption: {self.assumptions[0].rstrip('.')}.")
        if self.what_would_change_it:
            parts.append(f"It changes if {self.what_would_change_it[0].rstrip('.').lstrip().lower()}.")
        return " ".join(parts)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clamp(x) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return 0.5


def _utility(success: float, risk: float, effort: float) -> float:
    """Deterministic utility so ranking is reproducible (not LLM-dependent)."""
    return round(_clamp(success) * (1 - 0.6 * _clamp(risk)) * (1 - 0.3 * _clamp(effort)), 4)


def _avg(xs: list[float]) -> float:
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 4) if xs else 0.5


def _extract_json(text: str):
    """Pull a JSON object out of a model reply (handles ```json fences / prose).
    Returns the parsed object/list or None (graceful degrade on junk output)."""
    if not text:
        return None
    t = text.strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    m = re.search(r"\{.*\}", t, re.S) or re.search(r"\[.*\]", t, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _union(seqs) -> list[str]:
    out: list[str] = []
    for seq in seqs:
        for item in (seq or []):
            s = str(item).strip()
            if s and s not in out:
                out.append(s)
    return out


def _merge(results: list[dict]) -> dict:
    """Average numeric estimates per option across self-consistency samples."""
    if len(results) == 1:
        return results[0]
    acc: dict[str, dict] = {}
    order: list[str] = []
    for r in results:
        for o in (r.get("options") or []):
            name = str(o.get("name", "")).strip()
            if not name:
                continue
            key = name.lower()
            if key not in acc:
                acc[key] = {"name": name, "rationale": o.get("rationale", ""),
                            "sp": [], "risk": [], "effort": []}
                order.append(key)
            acc[key]["sp"].append(_clamp(o.get("success_probability")))
            acc[key]["risk"].append(_clamp(o.get("risk")))
            acc[key]["effort"].append(_clamp(o.get("effort")))
    options = [{
        "name": acc[k]["name"], "rationale": acc[k]["rationale"],
        "success_probability": _avg(acc[k]["sp"]),
        "risk": _avg(acc[k]["risk"]), "effort": _avg(acc[k]["effort"]),
    } for k in order]
    return {
        "options": options,
        "assumptions": _union(r.get("assumptions") for r in results),
        "confidence": _avg([_clamp(r.get("confidence")) for r in results]),
        "what_would_change_it": _union(r.get("what_would_change_it") for r in results),
    }


def _parse_result(data: dict, question: str) -> StrategyResult:
    opts = []
    for o in (data.get("options") or []):
        name = str(o.get("name", "")).strip()
        if not name:
            continue
        opts.append(StrategyOption(
            name=name,
            rationale=str(o.get("rationale", "")).strip(),
            success_probability=_clamp(o.get("success_probability")),
            risk=_clamp(o.get("risk")),
            effort=_clamp(o.get("effort")),
        ))
    return StrategyResult(
        question=question,
        options=opts,
        assumptions=[str(a).strip() for a in (data.get("assumptions") or []) if str(a).strip()],
        confidence=_clamp(data.get("confidence")),
        what_would_change_it=[str(w).strip() for w in (data.get("what_would_change_it") or []) if str(w).strip()],
        degraded=not opts,
    )


def _build_prompt(query: str, context: str, branches: int, depth: int) -> str:
    ctx = f"\n\nContext:\n{context.strip()}" if context and context.strip() else ""
    return (
        f"Decision/question: {query}{ctx}\n\n"
        f"Propose up to {branches} DISTINCT options. Consider up to {depth} step(s) of "
        f"downstream consequences (stay shallow). For each option give an honest "
        f"success_probability, risk, and effort, each between 0 and 1. Then state your "
        f"assumptions, an overall confidence (0-1), and what_would_change_it.\n\n"
        "Reply with ONLY this JSON (no prose):\n"
        '{\n'
        '  "options": [{"name": "...", "rationale": "...", "success_probability": 0.0, '
        '"risk": 0.0, "effort": 0.0}],\n'
        '  "assumptions": ["..."],\n'
        '  "confidence": 0.0,\n'
        '  "what_would_change_it": ["..."]\n'
        '}'
    )


async def _calibrate_and_persist(result: StrategyResult, query: str) -> None:
    """Persist the raw estimates and calibrate them against the owner's recorded
    outcomes (Phase 6). Fail-soft: if calibration is disabled or the DB is unavailable
    this is a no-op and the run proceeds with raw estimates.

    Calibration here = correcting the model's success estimates against the owner's OWN
    history — NOT retraining, NOT ground-truth simulation.
    """
    if result.degraded or not result.options:
        return
    try:
        from config import get_settings
        if not bool(getattr(get_settings(), "strategy_calibration_enabled", True)):
            return
        from agents import strategy_calibration as cal
    except Exception:  # noqa: BLE001
        return

    domain = cal.infer_domain(query)
    # Persist the RAW model estimates (pre-calibration) so future calibration measures
    # the model's own bias against realised outcomes.
    try:
        for o in result.options:
            o.utility = _utility(o.success_probability, o.risk, o.effort)
        await cal.persist_predictions(query, domain, result.options)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"strategy: prediction persist skipped ({e})")
    # Nudge the displayed success estimates toward the owner's own track record.
    try:
        adj, n = await cal.load_calibration(domain)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"strategy: calibration load skipped ({e})")
        return
    if n > 0 and adj:
        for o in result.options:
            o.success_probability = cal.apply_adjustment(o.success_probability, adj)
        result.calibrated_on = n


async def run_strategy(query: str, *, context: str = "") -> StrategyResult:
    """Run bounded strategic deliberation and return a ranked, honest StrategyResult."""
    from config import get_settings
    cfg = get_settings()
    branches = max(2, int(getattr(cfg, "strategy_branches", 4)))
    depth = min(max(1, int(getattr(cfg, "strategy_depth", 1))), 2)   # hard ceiling 2
    samples = max(1, int(getattr(cfg, "strategy_self_consistency", 1)))
    deep = bool(getattr(cfg, "strategy_deep_synthesis", True))

    prompt = _build_prompt(query, context, branches, depth)
    parsed: list[dict] = []
    for _ in range(samples):
        try:
            raw = await chat_complete(
                [{"role": "system", "content": _SYS}, {"role": "user", "content": prompt}],
                use_deep=deep, temperature=0.4,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"strategy model call failed: {e}")
            continue
        data = _extract_json(raw)
        if isinstance(data, dict):
            parsed.append(data)

    if not parsed:
        return StrategyResult(
            question=query, degraded=True, confidence=0.0,
            assumptions=["The model output couldn't be parsed into options."],
            what_would_change_it=["A clearer question, or retrying."],
        )

    result = _parse_result(_merge(parsed), query)
    # Phase 6: persist the raw estimates + calibrate against the owner's own outcomes.
    await _calibrate_and_persist(result, query)
    for o in result.options:
        o.utility = _utility(o.success_probability, o.risk, o.effort)
    result.options.sort(key=lambda o: o.utility, reverse=True)
    return result


__all__ = ["is_strategy_request", "run_strategy", "StrategyResult", "StrategyOption"]
