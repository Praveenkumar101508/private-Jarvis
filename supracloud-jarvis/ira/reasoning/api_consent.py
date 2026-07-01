"""
ira/reasoning/api_consent.py — the external-API consent, privacy and audit layer.

This module owns everything to do with *whether* IRA may leave the machine:

  * the privacy / consent environment switches and their safe defaults;
  * the user-facing Deep Intelligence Mode consent copy;
  * :func:`apply_consent` — turning a user's Approve / Local-only answer into a
    final :class:`~reasoning.model_router.ModelRouteDecision`;
  * the runtime execution gate (:func:`run_decision` + executor registry) that
    makes external use impossible unless it was explicitly enabled and wired;
  * a small **structured consent audit hook** (:func:`record_consent_event`)
    that records *safe metadata only* — never prompts, never secrets — every
    time Deep Intelligence Mode is offered, approved, declined, blocked, or
    found unavailable.

It deliberately does **not** import :class:`ModelRouteDecision` at runtime
(``apply_consent`` only needs :func:`dataclasses.replace`, ``run_decision`` only
reads attributes), so ``model_router`` can import and re-export from here without
a circular import. All public names are re-exported from ``reasoning.model_router``
for backward compatibility — existing callers keep importing from there unchanged.
"""
from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, Mapping, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids a runtime import cycle
    from reasoning.model_router import ModelRouteDecision

logger = logging.getLogger("ira.reasoning.consent_audit")

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


def _external_target(env: Mapping[str, str]) -> tuple[str, str]:
    provider = (env.get(EXTERNAL_PROVIDER_ENV) or "anthropic").strip() or "anthropic"
    model = (env.get(EXTERNAL_MODEL_ENV) or "").strip()
    if not model:
        # A neutral placeholder; the actual provider/model is wired by the caller.
        model = f"{provider}:external-frontier"
    return provider, model


# ── Structured consent audit hook ───────────────────────────────────────────────
# A tiny, dependency-free audit seam. It records only *safe metadata* about each
# Deep Intelligence Mode consent decision so external-use choices are independently
# queryable. It NEVER receives prompt content, context, or secrets. By default it
# writes one structured INFO log line; a host app can call
# ``register_consent_audit_sink()`` to forward events into the full audit/event
# system (e.g. ``utils.security_events.emit_event``) later.

#: The machine-readable outcomes an audit event can record.
CONSENT_OFFERED = "offered"        # IRA offered Deep Intelligence Mode (consent pending)
CONSENT_APPROVED = "approved"      # user approved AND external is allowed -> going external
CONSENT_DECLINED = "declined"      # user chose Local Mode only
CONSENT_BLOCKED = "blocked"        # user approved but config/policy forbids external -> stayed local
CONSENT_UNAVAILABLE = "unavailable"  # external requested at run time but not executable


@dataclass(frozen=True)
class ConsentAuditEvent:
    """Safe, structured record of one consent decision.

    Contains **no** prompt text, context, or secret — only routing metadata that
    is safe to persist and query.
    """

    timestamp: str                      # ISO-8601 UTC, second precision
    reason_code: str                    # one of the CONSENT_* codes above
    privacy_mode: str                   # active IRA_PRIVACY_MODE
    selected_mode: str                  # resolved ModelMode (e.g. "local_reasoning")
    selected_model: str                 # concrete model name (local or external target)
    consent_required: bool              # was explicit user consent required?
    consent_approved: Optional[bool]    # True/False once answered; None when not applicable
    provider: Optional[str]             # external provider name — only when approved+external
    estimated_cost_level: str           # "none" | "low" | "medium" | "high"


#: Sink signature: ``fn(event: ConsentAuditEvent) -> None``.
AuditSink = Callable[["ConsentAuditEvent"], None]

_AUDIT_SINK: Optional[AuditSink] = None  # None -> the default structured-log sink


def _default_log_sink(event: ConsentAuditEvent) -> None:
    """Default sink: emit one structured INFO line (no prompt, no secret)."""
    logger.info("consent_audit %s", asdict(event))


def register_consent_audit_sink(fn: Optional[AuditSink]) -> None:
    """Register the callable that receives every :class:`ConsentAuditEvent`.

    Pass ``None`` to fall back to the default structured-log sink. This is the
    seam a host app uses to forward consent decisions into the full audit system.
    The sink must accept a single :class:`ConsentAuditEvent`; it is called
    fail-soft (any exception is logged and swallowed, never propagated to routing).
    """
    global _AUDIT_SINK
    _AUDIT_SINK = fn


def reset_consent_audit_sink() -> None:
    """Restore the default structured-log sink (tests / lockdown)."""
    global _AUDIT_SINK
    _AUDIT_SINK = None


def record_consent_event(
    *,
    reason_code: str,
    privacy_mode: str,
    selected_mode: str,
    selected_model: str,
    consent_required: bool,
    consent_approved: Optional[bool] = None,
    provider: Optional[str] = None,
    estimated_cost_level: str = "none",
) -> ConsentAuditEvent:
    """Build and dispatch a :class:`ConsentAuditEvent`, returning it.

    Dispatch is fail-soft: a broken sink never disturbs routing. Only safe
    metadata is accepted — there is deliberately no parameter for prompt text.
    """
    event = ConsentAuditEvent(
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        reason_code=reason_code,
        privacy_mode=privacy_mode,
        selected_mode=str(selected_mode),
        selected_model=selected_model,
        consent_required=consent_required,
        consent_approved=consent_approved,
        provider=provider,
        estimated_cost_level=estimated_cost_level,
    )
    sink = _AUDIT_SINK or _default_log_sink
    try:
        sink(event)
    except Exception as exc:  # noqa: BLE001 - audit must never break routing
        logger.warning("consent audit sink failed (fail-soft): %s", exc)
    return event


def _audit_from_decision(
    decision: "ModelRouteDecision",
    *,
    reason_code: str,
    consent_approved: Optional[bool] = None,
    provider: Optional[str] = None,
) -> ConsentAuditEvent:
    """Record an audit event from a decision's safe metadata fields."""
    return record_consent_event(
        reason_code=reason_code,
        privacy_mode=decision.privacy_level,
        selected_mode=str(decision.selected_mode),
        selected_model=decision.selected_model,
        consent_required=decision.requires_api_consent,
        consent_approved=consent_approved,
        provider=provider,
        estimated_cost_level=decision.estimated_cost_level,
    )


# ── Consent gate ────────────────────────────────────────────────────────────────

def apply_consent(
    decision: "ModelRouteDecision",
    approved: bool,
    *,
    env: Optional[Mapping[str, str]] = None,
) -> "ModelRouteDecision":
    """Resolve a consent prompt into a final decision.

    * ``approved=False`` → stay local (continue with the locally-selected model);
      ``requires_api_consent`` is cleared.
    * ``approved=True`` but the ``IRA_ALLOW_EXTERNAL_API`` master switch is off →
      stay local (config forbids external use). External is NEVER used silently.
    * ``approved=True`` and allowed → switch to the external provider/model.

    Every outcome emits a structured consent audit event (safe metadata only).
    """
    env = os.environ if env is None else env

    if not approved:
        _audit_from_decision(decision, reason_code=CONSENT_DECLINED, consent_approved=False)
        return replace(
            decision,
            requires_api_consent=False,
            reason=decision.reason + "; user chose Local Mode only",
            provider="local",
        )

    if not external_api_allowed(env):
        _audit_from_decision(decision, reason_code=CONSENT_BLOCKED, consent_approved=True)
        return replace(
            decision,
            requires_api_consent=False,
            reason=decision.reason + "; external API disabled by config (IRA_ALLOW_EXTERNAL_API=false) — staying local",
            provider="local",
        )

    provider, model = _external_target(env)
    final = replace(
        decision,
        provider="external",
        selected_model=model,
        fallback_model=decision.selected_model,   # the local model remains the safety net
        requires_api_consent=False,
        estimated_cost_level="high",
        reason=decision.reason + f"; user approved Deep Intelligence Mode -> {provider}",
    )
    _audit_from_decision(
        final, reason_code=CONSENT_APPROVED, consent_approved=True, provider=provider
    )
    return final


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
    decision: "ModelRouteDecision",
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
    A blocked external run is recorded as an ``unavailable`` consent audit event.
    """
    env = os.environ if env is None else env
    if decision.provider == "local":
        return local_runner(decision)

    # provider == "external" — re-check the master switch at execution time.
    if not external_api_allowed(env):
        _audit_from_decision(
            decision, reason_code=CONSENT_UNAVAILABLE, consent_approved=True
        )
        raise ExternalExecutorNotConfigured(
            "External execution blocked: IRA_ALLOW_EXTERNAL_API is false."
        )
    if _EXTERNAL_EXECUTOR is None:
        _audit_from_decision(
            decision, reason_code=CONSENT_UNAVAILABLE, consent_approved=True
        )
        raise ExternalExecutorNotConfigured(
            "External execution blocked: no external executor is registered. "
            "Deep Intelligence Mode is decision-only by default; the host app must "
            "call register_external_executor() to enable it."
        )
    return _EXTERNAL_EXECUTOR(decision, system, prompt)


__all__ = [
    # Consent / privacy config.
    "ALLOW_EXTERNAL_ENV",
    "REQUIRE_CONSENT_ENV",
    "PRIVACY_MODE_ENV",
    "EXTERNAL_PROVIDER_ENV",
    "EXTERNAL_MODEL_ENV",
    "DEFAULT_PRIVACY_MODE",
    "CONSENT_MESSAGE",
    "consent_message",
    "privacy_mode",
    "external_api_allowed",
    "consent_required",
    # Consent gate.
    "apply_consent",
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
    # Execution gate.
    "ExternalExecutorNotConfigured",
    "register_external_executor",
    "clear_external_executor",
    "run_decision",
]
