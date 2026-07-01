"""Structured consent audit hook — safe, queryable records of Deep Intelligence
Mode decisions.

Proves that offering, approving, declining, blocking, and finding external
execution unavailable each emit exactly one :class:`ConsentAuditEvent`, that the
events carry only safe metadata (no prompt text, no secrets), and that a broken
sink can never disturb routing.
"""
from dataclasses import fields

import pytest

from reasoning.model_availability import ModelAvailability
from reasoning.model_profiles import reload_config
from reasoning.model_router import (
    CONSENT_APPROVED,
    CONSENT_BLOCKED,
    CONSENT_DECLINED,
    CONSENT_OFFERED,
    CONSENT_UNAVAILABLE,
    ConsentAuditEvent,
    ExternalExecutorNotConfigured,
    apply_consent,
    clear_external_executor,
    register_consent_audit_sink,
    reset_consent_audit_sink,
    route,
    run_decision,
)

UNKNOWN = ModelAvailability(reachable=False, models=frozenset(), source="test")
VERY_HARD = "do a very deep architecture and security refactor of the entire platform"
SIMPLE = "hi"
SECRET = "sk-super-secret-key-should-never-be-logged"


@pytest.fixture(autouse=True)
def _fresh():
    reload_config()
    clear_external_executor()
    events: list[ConsentAuditEvent] = []
    register_consent_audit_sink(events.append)
    yield events
    reset_consent_audit_sink()
    clear_external_executor()
    reload_config()


def _hard(env):
    return route(VERY_HARD, env=env, availability=UNKNOWN)


def test_offer_emits_offered_event(_fresh):
    _hard(env={})
    assert len(_fresh) == 1
    ev = _fresh[0]
    assert ev.reason_code == CONSENT_OFFERED
    assert ev.consent_required is True
    assert ev.consent_approved is None
    assert ev.provider is None
    assert ev.estimated_cost_level == "none"
    assert ev.privacy_mode == "local_first"
    assert ev.selected_mode == "local_reasoning"


def test_no_event_for_ordinary_local_route(_fresh):
    # A simple request never offers Deep Intelligence Mode -> no audit noise.
    route(SIMPLE, env={}, availability=UNKNOWN)
    assert _fresh == []


def test_local_only_privacy_emits_no_event(_fresh):
    _hard(env={"IRA_PRIVACY_MODE": "local_only"})
    assert _fresh == []


def test_decline_emits_declined_event(_fresh):
    d = _hard(env={})
    _fresh.clear()  # drop the "offered" event; focus on the decision
    apply_consent(d, approved=False, env={})
    assert len(_fresh) == 1
    ev = _fresh[0]
    assert ev.reason_code == CONSENT_DECLINED
    assert ev.consent_approved is False
    assert ev.provider is None


def test_blocked_by_master_switch_emits_blocked_event(_fresh):
    d = _hard(env={})
    _fresh.clear()
    apply_consent(d, approved=True, env={})  # master switch off
    assert len(_fresh) == 1
    ev = _fresh[0]
    assert ev.reason_code == CONSENT_BLOCKED
    assert ev.consent_approved is True
    assert ev.provider is None
    assert ev.estimated_cost_level == "none"


def test_approved_emits_approved_event_with_provider(_fresh):
    env = {
        "IRA_ALLOW_EXTERNAL_API": "true",
        "IRA_EXTERNAL_API_PROVIDER": "anthropic",
        "IRA_EXTERNAL_API_MODEL": "claude-frontier",
    }
    d = _hard(env=env)
    _fresh.clear()
    apply_consent(d, approved=True, env=env)
    assert len(_fresh) == 1
    ev = _fresh[0]
    assert ev.reason_code == CONSENT_APPROVED
    assert ev.consent_approved is True
    assert ev.provider == "anthropic"
    assert ev.selected_model == "claude-frontier"
    assert ev.estimated_cost_level == "high"


def test_unavailable_external_run_emits_unavailable_event(_fresh):
    env = {
        "IRA_ALLOW_EXTERNAL_API": "true",
        "IRA_EXTERNAL_API_PROVIDER": "anthropic",
        "IRA_EXTERNAL_API_MODEL": "claude-frontier",
    }
    d = _hard(env=env)
    final = apply_consent(d, approved=True, env=env)
    _fresh.clear()
    # No executor registered -> external run must fail AND be audited.
    with pytest.raises(ExternalExecutorNotConfigured):
        run_decision(final, local_runner=lambda dec: "local", env=env)
    assert len(_fresh) == 1
    assert _fresh[0].reason_code == CONSENT_UNAVAILABLE


def test_local_run_emits_no_event(_fresh):
    d = _hard(env={})
    local_final = apply_consent(d, approved=False, env={})
    _fresh.clear()
    out = run_decision(local_final, local_runner=lambda dec: "local-answer", env={})
    assert out == "local-answer"
    assert _fresh == []


def test_audit_event_carries_no_prompt_or_secret(_fresh):
    # Route a very-hard prompt that embeds a secret; approve external. No audit
    # field may contain the prompt text or the secret.
    env = {
        "IRA_ALLOW_EXTERNAL_API": "true",
        "IRA_EXTERNAL_API_PROVIDER": "anthropic",
        "IRA_EXTERNAL_API_MODEL": "claude-frontier",
    }
    prompt = f"{VERY_HARD} using the api key {SECRET}"
    d = route(prompt, env=env, availability=UNKNOWN)
    apply_consent(d, approved=True, env=env)
    assert _fresh, "expected at least one audit event"
    audit_field_names = {f.name for f in fields(ConsentAuditEvent)}
    assert "prompt" not in audit_field_names  # no prompt field exists at all
    for ev in _fresh:
        blob = repr(ev)
        assert SECRET not in blob
        assert "refactor" not in blob  # a distinctive word from the prompt body


def test_broken_sink_never_breaks_routing(_fresh):
    def boom(_event):
        raise RuntimeError("sink exploded")

    register_consent_audit_sink(boom)
    # Offering + applying consent must still succeed despite the failing sink.
    d = _hard(env={})
    final = apply_consent(d, approved=False, env={})
    assert final.provider == "local"


def test_default_sink_is_used_after_reset(_fresh):
    # After reset there is no custom sink; recording must not raise.
    reset_consent_audit_sink()
    d = _hard(env={})
    assert d.provider == "local"
