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

The consent gate, privacy switches, execution gate, and structured consent audit
hook live in :mod:`reasoning.api_consent`; they are re-exported here so existing
callers (``from reasoning.model_router import apply_consent`` etc.) keep working
unchanged.

The seven modes and three profiles live in ``config/model_profiles.yaml``; this
module only decides *which mode* a task needs and resolves the concrete model
through the profile + availability layers.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
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

# Consent / privacy / execution-gate / audit primitives now live in api_consent
# and are re-exported here for backward compatibility.
from reasoning.api_consent import (
    ALLOW_EXTERNAL_ENV,
    AuditSink,
    CONSENT_APPROVED,
    CONSENT_BLOCKED,
    CONSENT_DECLINED,
    CONSENT_MESSAGE,
    CONSENT_OFFERED,
    CONSENT_UNAVAILABLE,
    ConsentAuditEvent,
    EXTERNAL_MODEL_ENV,
    EXTERNAL_PROVIDER_ENV,
    ExternalExecutorNotConfigured,
    PRIVACY_MODE_ENV,
    REQUIRE_CONSENT_ENV,
    apply_consent,
    clear_external_executor,
    consent_message,
    consent_required,
    external_api_allowed,
    privacy_mode,
    record_consent_event,
    register_consent_audit_sink,
    register_external_executor,
    reset_consent_audit_sink,
    run_decision,
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
    :func:`apply_consent` with the user's answer. Offering Deep Intelligence Mode
    emits a structured consent audit event (safe metadata only).
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

    decision = ModelRouteDecision(
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

    if offering:
        # Record that Deep Intelligence Mode was offered (consent still pending).
        record_consent_event(
            reason_code=CONSENT_OFFERED,
            privacy_mode=priv,
            selected_mode=str(used_mode),
            selected_model=selected_model,
            consent_required=True,
            consent_approved=None,
            provider=None,
            estimated_cost_level="none",
        )

    return decision


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
    # Structured consent audit hook.
    "ConsentAuditEvent",
    "AuditSink",
    "CONSENT_OFFERED",
    "CONSENT_APPROVED",
    "CONSENT_DECLINED",
    "CONSENT_BLOCKED",
    "CONSENT_UNAVAILABLE",
    "record_consent_event",
    "register_consent_audit_sink",
    "reset_consent_audit_sink",
    # Env-var name constants (re-exported).
    "ALLOW_EXTERNAL_ENV",
    "REQUIRE_CONSENT_ENV",
    "PRIVACY_MODE_ENV",
    "EXTERNAL_PROVIDER_ENV",
    "EXTERNAL_MODEL_ENV",
]
