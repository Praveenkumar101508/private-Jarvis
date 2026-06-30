"""
ira/reasoning/model_router.py — pick the right local model for the task.

This is the brain of IRA's smart model selection. Given a request it produces a
:class:`ModelRouteDecision` naming the local model that should answer, the local
fallback if that model is missing, and whether IRA should *offer* (never silently
use) an external frontier model for a very hard task.

Local-first, consent-gated, non-breaking:
  * Every route :func:`route` returns is **local** — ``provider == "local"``.
    The router never selects an external API model.
  * External use is reached only through :func:`apply_consent` with
    ``approved=True`` AND the ``IRA_ALLOW_EXTERNAL_API`` master switch on. A
    decline (or the switch being off) keeps the answer local.
  * Selection layers on top of :mod:`reasoning.model_profiles` (which model name)
    and :mod:`reasoning.model_availability` (is it installed) — it does not touch
    the existing ``utils.llm`` chat flow.

The seven modes and three profiles live in ``config/model_profiles.yaml``; this
module only decides *which mode* a task needs and resolves the concrete model
through the profile + availability layers.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Mapping, Optional

from reasoning.model_availability import (
    ModelAvailability,
    available_or_unknown,
    get_availability,
)
from reasoning.model_profiles import (
    ModelMode,
    active_profile_name,
    embedding_fallback_model,
    fallback_chain,
    model_for,
)

# ── Consent / privacy environment switches ──────────────────────────────────────
ALLOW_EXTERNAL_ENV = "IRA_ALLOW_EXTERNAL_API"      # master off-switch (default false)
REQUIRE_CONSENT_ENV = "IRA_REQUIRE_API_CONSENT"    # ask before any external (default true)
PRIVACY_MODE_ENV = "IRA_PRIVACY_MODE"              # local_only | local_first | external_ok
EXTERNAL_PROVIDER_ENV = "IRA_EXTERNAL_API_PROVIDER"
EXTERNAL_MODEL_ENV = "IRA_EXTERNAL_API_MODEL"

DEFAULT_PRIVACY_MODE = "local_first"

#: Shown to the user when IRA offers Deep Intelligence Mode for a very hard task.
CONSENT_MESSAGE = (
    "IRA can answer this locally, but this request deserves deeper reasoning.\n\n"
    "For the strongest result, I can activate Deep Intelligence Mode using an "
    "external frontier model. This may send the necessary prompt/context to the "
    "selected API provider and may use paid tokens.\n\n"
    "Your privacy stays in your control.\n\n"
    "Choose one:\n"
    "- Approve Deep Intelligence Mode for this request\n"
    "- Continue with Local Mode only\n\n"
    "Reply: 'Approve' or 'Local only'."
)

# ── Task-classification vocabulary ──────────────────────────────────────────────
_CODING_KEYWORDS = (
    "code", "coding", "debug", "refactor", "implement", "function ", "bug",
    "stack trace", "traceback", "compile", "unit test", "pytest", "repo",
    "pull request", "git ", "regex", "endpoint", "class ", "method", "exception",
    "lint", "syntax", "snippet", "script", "build error",
)
_REASONING_KEYWORDS = (
    "architecture", "architect", "design a", "security", "audit", "threat model",
    "trade-off", "tradeoff", "scalab", "strategy", "prove", "root cause",
    "algorithm", "optimi", "complexity", "deeply", "reason through", "multi-step",
    "step by step", "rigorous", "vulnerabilit", "exploit",
)
_VERY_HARD_KEYWORDS = (
    "very deep", "very hard", "frontier", "world-class", "world class",
    "extremely hard", "phd", "research-grade", "research grade", "novel proof",
    "deep architecture", "deep security", "hardest", "most complex",
)
_FAST_KEYWORDS = (
    "hi", "hello", "hey", "thanks", "thank you", "what time", "status", "ping",
    "good morning", "good night", "bye", "who are you", "how are you",
)
_MEMORY_KEYWORDS = (
    "search my memory", "my memory", "my documents", "my notes", "recall",
    "what did i", "remember when", "look up in my", "from my files",
)


def _contains(text: str, needles) -> bool:
    return any(n in text for n in needles)


# ── The decision object ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ModelRouteDecision:
    """The outcome of routing a single request.

    ``provider`` is always ``"local"`` for anything :func:`route` returns; only
    :func:`apply_consent` (approved + allowed) can produce ``"external"``.
    """

    selected_mode: ModelMode
    selected_model: str
    fallback_model: Optional[str]
    reason: str
    confidence: float
    requires_api_consent: bool
    estimated_cost_level: str          # "none" (local) | "low" | "medium" | "high"
    privacy_level: str                 # the active IRA_PRIVACY_MODE
    allow_local_fallback: bool
    provider: str = "local"            # "local" | "external"

    @property
    def is_local(self) -> bool:
        return self.provider == "local"


# ── Config readers ──────────────────────────────────────────────────────────────

def _bool_env(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def privacy_mode(env: Optional[Mapping[str, str]] = None) -> str:
    env = os.environ if env is None else env
    val = (env.get(PRIVACY_MODE_ENV) or "").strip().lower()
    return val or DEFAULT_PRIVACY_MODE


def external_api_allowed(env: Optional[Mapping[str, str]] = None) -> bool:
    """Master switch: may IRA EVER use an external API (default: no)."""
    env = os.environ if env is None else env
    return _bool_env(env, ALLOW_EXTERNAL_ENV, False)


def consent_required(env: Optional[Mapping[str, str]] = None) -> bool:
    env = os.environ if env is None else env
    return _bool_env(env, REQUIRE_CONSENT_ENV, True)


def consent_message() -> str:
    return CONSENT_MESSAGE


# ── Task classification ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _Classification:
    mode: ModelMode
    very_hard: bool
    reason: str
    confidence: float


def classify_task(
    prompt: str = "",
    *,
    has_image: bool = False,
    is_memory_search: bool = False,
    think_mode: bool = False,
    deep_search: bool = False,
    task_type: Optional[str] = None,
) -> _Classification:
    """Decide which :class:`ModelMode` a request needs (no model resolution yet)."""
    text = (prompt or "").lower()
    words = text.split()

    # 0) Explicit task_type override always wins.
    explicit = {
        "vision": ModelMode.LOCAL_VISION,
        "image": ModelMode.LOCAL_VISION,
        "memory": ModelMode.MEMORY_EMBEDDING,
        "embedding": ModelMode.MEMORY_EMBEDDING,
        "rag": ModelMode.MEMORY_EMBEDDING,
        "coding": ModelMode.LOCAL_CODING,
        "code": ModelMode.LOCAL_CODING,
        "reasoning": ModelMode.LOCAL_REASONING,
        "architecture": ModelMode.LOCAL_REASONING,
        "fast": ModelMode.LOCAL_FAST,
        "chat": ModelMode.LOCAL_FAST,
        "main": ModelMode.LOCAL_MAIN,
    }
    if task_type:
        key = task_type.strip().lower()
        if key == "very_hard":
            return _Classification(ModelMode.LOCAL_REASONING, True, "explicit very-hard task", 0.95)
        if key in explicit:
            return _Classification(explicit[key], False, f"explicit task_type={key}", 0.95)

    very_hard = _contains(text, _VERY_HARD_KEYWORDS)

    # 1) Vision input — a picture beats any text heuristic.
    if has_image:
        return _Classification(ModelMode.LOCAL_VISION, very_hard, "image/PDF input present", 0.95)

    # 2) Memory / RAG retrieval.
    if is_memory_search or _contains(text, _MEMORY_KEYWORDS):
        return _Classification(ModelMode.MEMORY_EMBEDDING, False, "memory/RAG retrieval", 0.9)

    # 3) Very hard tasks go to the deep brain even if they also mention code
    #    (e.g. "very deep architecture/security refactor" -> reason, then offer API).
    if very_hard:
        return _Classification(ModelMode.LOCAL_REASONING, True, "very hard task", 0.85)

    # 4) Coding / repo work.
    if _contains(text, _CODING_KEYWORDS):
        return _Classification(ModelMode.LOCAL_CODING, very_hard, "code-related request", 0.85)

    # 5) Deep reasoning (toggles or vocabulary, or a very long prompt).
    if think_mode or deep_search or _contains(text, _REASONING_KEYWORDS) or len(words) > 120:
        why = "think/deep-search toggle" if (think_mode or deep_search) else "reasoning-depth request"
        return _Classification(ModelMode.LOCAL_REASONING, very_hard, why, 0.8)

    # 6) Clearly simple chat → fast.
    if (_contains(text, _FAST_KEYWORDS) and len(words) <= 12) or len(words) <= 5:
        return _Classification(ModelMode.LOCAL_FAST, False, "short/simple request", 0.8)

    # 7) Default: a normal, useful answer.
    return _Classification(ModelMode.LOCAL_MAIN, very_hard, "general request (default)", 0.7)


# ── Model resolution with local fallback ────────────────────────────────────────

def resolve_model(
    mode: ModelMode,
    *,
    env: Optional[Mapping[str, str]] = None,
    availability: Optional[ModelAvailability] = None,
) -> tuple[ModelMode, str, Optional[str]]:
    """Resolve ``mode`` to (used_mode, selected_model, next_fallback_model).

    Walks the mode's local fallback chain, picking the first model that is
    available-or-unknown (optimistic when Ollama can't be probed). Embeddings
    degrade to the lighter embedding model rather than a chat model.
    """
    env = os.environ if env is None else env

    # Embeddings have their own (non-chat) fallback.
    if mode == ModelMode.MEMORY_EMBEDDING:
        primary = model_for(ModelMode.MEMORY_EMBEDDING, env=env)
        fb = embedding_fallback_model()
        if available_or_unknown(primary, env=env, availability=availability):
            return ModelMode.MEMORY_EMBEDDING, primary, (fb if fb != primary else None)
        return ModelMode.MEMORY_EMBEDDING, fb, None

    chain = fallback_chain(mode)
    resolved: list[tuple[ModelMode, str]] = []
    for m in chain:
        resolved.append((m, model_for(m, env=env)))

    chosen_idx = None
    for idx, (m, model) in enumerate(resolved):
        if available_or_unknown(model, env=env, availability=availability):
            chosen_idx = idx
            break
    if chosen_idx is None:
        # Nothing available even optimistically — land on the terminal tiny model.
        chosen_idx = len(resolved) - 1

    used_mode, selected_model = resolved[chosen_idx]
    fallback_model = resolved[chosen_idx + 1][1] if chosen_idx + 1 < len(resolved) else None
    return used_mode, selected_model, fallback_model


# ── Top-level routing ───────────────────────────────────────────────────────────

def route(
    prompt: str = "",
    *,
    has_image: bool = False,
    is_memory_search: bool = False,
    think_mode: bool = False,
    deep_search: bool = False,
    task_type: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    availability: Optional[ModelAvailability] = None,
) -> ModelRouteDecision:
    """Route a request to a **local** model, offering external only when warranted.

    The returned decision is always local. ``requires_api_consent`` is True only
    when the task is very hard AND privacy mode permits offering an external
    model — in which case the caller should show :data:`CONSENT_MESSAGE` and call
    :func:`apply_consent` with the user's answer.
    """
    env = os.environ if env is None else env
    if availability is None:
        availability = get_availability(env=env)

    cls = classify_task(
        prompt,
        has_image=has_image,
        is_memory_search=is_memory_search,
        think_mode=think_mode,
        deep_search=deep_search,
        task_type=task_type,
    )

    used_mode, selected_model, fallback_model = resolve_model(
        cls.mode, env=env, availability=availability
    )

    priv = privacy_mode(env)
    # Offer external only for a very hard task and only when privacy allows it.
    offering = cls.very_hard and priv in {"local_first", "external_ok"}

    reason = cls.reason
    if used_mode != cls.mode:
        reason = f"{cls.reason}; '{cls.mode}' unavailable, fell back to '{used_mode}'"
    if offering:
        reason += "; very hard — offering Deep Intelligence Mode (consent required)"

    return ModelRouteDecision(
        selected_mode=used_mode,
        selected_model=selected_model,
        fallback_model=fallback_model,
        reason=reason,
        confidence=cls.confidence,
        requires_api_consent=offering,
        estimated_cost_level="none",          # local selection is always free
        privacy_level=priv,
        allow_local_fallback=True,
        provider="local",
    )


# ── Consent gate ────────────────────────────────────────────────────────────────

def _external_target(env: Mapping[str, str]) -> tuple[str, str]:
    provider = (env.get(EXTERNAL_PROVIDER_ENV) or "anthropic").strip() or "anthropic"
    model = (env.get(EXTERNAL_MODEL_ENV) or "").strip()
    if not model:
        # A neutral placeholder; the actual provider/model is wired by the caller.
        model = f"{provider}:external-frontier"
    return provider, model


def apply_consent(
    decision: ModelRouteDecision,
    approved: bool,
    *,
    env: Optional[Mapping[str, str]] = None,
) -> ModelRouteDecision:
    """Resolve a consent prompt into a final decision.

    * ``approved=False`` → stay local (continue with the locally-selected model);
      ``requires_api_consent`` is cleared.
    * ``approved=True`` but the ``IRA_ALLOW_EXTERNAL_API`` master switch is off →
      stay local (config forbids external use). External is NEVER used silently.
    * ``approved=True`` and allowed → switch to the external provider/model.
    """
    env = os.environ if env is None else env

    if not approved:
        return replace(
            decision,
            requires_api_consent=False,
            reason=decision.reason + "; user chose Local Mode only",
            provider="local",
        )

    if not external_api_allowed(env):
        return replace(
            decision,
            requires_api_consent=False,
            reason=decision.reason + "; external API disabled by config (IRA_ALLOW_EXTERNAL_API=false) — staying local",
            provider="local",
        )

    provider, model = _external_target(env)
    return replace(
        decision,
        provider="external",
        selected_model=model,
        fallback_model=decision.selected_model,   # the local model remains the safety net
        requires_api_consent=False,
        estimated_cost_level="high",
        reason=decision.reason + f"; user approved Deep Intelligence Mode -> {provider}",
    )


# ── Execution gate (defence in depth) ───────────────────────────────────────────
# A second, runtime guard so that an external decision can NEVER reach the network
# unless: (1) the decision is provider=="external" (only apply_consent(approved)
# produces it), (2) the IRA_ALLOW_EXTERNAL_API master switch is on, and (3) an
# external executor has been explicitly registered by the host application. No
# external executor ships by default, so Deep Intelligence Mode is decision-only
# out of the box — it cannot call out even if every other check were bypassed.

class ExternalExecutorNotConfigured(RuntimeError):
    """Raised when an external decision is run without a registered, allowed executor."""


_EXTERNAL_EXECUTOR = None  # set via register_external_executor()


def register_external_executor(fn) -> None:
    """Register the callable that performs an external (frontier) call.

    ``fn(decision, system, prompt) -> str``. Registering is an explicit, deliberate
    act by the host app; until then external execution is impossible.
    """
    global _EXTERNAL_EXECUTOR
    _EXTERNAL_EXECUTOR = fn


def clear_external_executor() -> None:
    """Remove any registered external executor (tests / lockdown)."""
    global _EXTERNAL_EXECUTOR
    _EXTERNAL_EXECUTOR = None


def run_decision(
    decision: ModelRouteDecision,
    *,
    local_runner,
    system: str = "",
    prompt: str = "",
    env: Optional[Mapping[str, str]] = None,
) -> str:
    """Execute a decision. Local decisions call ``local_runner(decision)``.

    External decisions are gated again here: they require the master switch on AND
    a registered executor, else :class:`ExternalExecutorNotConfigured` is raised.
    External use is therefore never silent — there is no default code path to it.
    """
    env = os.environ if env is None else env
    if decision.provider == "local":
        return local_runner(decision)

    # provider == "external" — re-check the master switch at execution time.
    if not external_api_allowed(env):
        raise ExternalExecutorNotConfigured(
            "External execution blocked: IRA_ALLOW_EXTERNAL_API is false."
        )
    if _EXTERNAL_EXECUTOR is None:
        raise ExternalExecutorNotConfigured(
            "External execution blocked: no external executor is registered. "
            "Deep Intelligence Mode is decision-only by default; the host app must "
            "call register_external_executor() to enable it."
        )
    return _EXTERNAL_EXECUTOR(decision, system, prompt)


__all__ = [
    "ModelRouteDecision",
    "CONSENT_MESSAGE",
    "classify_task",
    "resolve_model",
    "route",
    "apply_consent",
    "consent_message",
    "privacy_mode",
    "external_api_allowed",
    "consent_required",
    # Execution gate (M2).
    "ExternalExecutorNotConfigured",
    "register_external_executor",
    "clear_external_executor",
    "run_decision",
]
