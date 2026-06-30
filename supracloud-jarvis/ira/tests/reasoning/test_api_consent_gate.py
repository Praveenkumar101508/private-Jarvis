"""Phase 3 — the external-API consent gate.

Proves IRA never reaches an external API without explicit consent, and that a
decline (or the master switch being off) keeps the answer local.
"""
import pytest

from reasoning.model_availability import ModelAvailability
from reasoning.model_profiles import ModelMode, reload_config
from reasoning.model_router import (
    CONSENT_MESSAGE,
    apply_consent,
    consent_message,
    consent_required,
    external_api_allowed,
    route,
)

UNKNOWN = ModelAvailability(reachable=False, models=frozenset(), source="test")
VERY_HARD = "do a very deep architecture and security refactor of the entire platform"


@pytest.fixture(autouse=True)
def _fresh():
    reload_config()
    yield
    reload_config()


def _hard(env):
    return route(VERY_HARD, env=env, availability=UNKNOWN)


def test_defaults_are_local_first_and_consent_required():
    assert external_api_allowed(env={}) is False
    assert consent_required(env={}) is True


def test_route_never_returns_external_provider():
    for prompt in ["hi", "debug this code", VERY_HARD, "design an architecture"]:
        d = route(prompt, env={}, availability=UNKNOWN)
        assert d.provider == "local"


def test_very_hard_requires_consent_by_default():
    d = _hard(env={})
    assert d.requires_api_consent is True
    assert d.selected_mode == ModelMode.LOCAL_REASONING
    assert d.provider == "local"            # not external until approved


def test_local_only_privacy_never_offers_api():
    d = _hard(env={"IRA_PRIVACY_MODE": "local_only"})
    assert d.requires_api_consent is False
    assert d.provider == "local"


def test_decline_continues_locally():
    d = _hard(env={})
    final = apply_consent(d, approved=False, env={})
    assert final.provider == "local"
    assert final.requires_api_consent is False
    assert final.selected_mode == ModelMode.LOCAL_REASONING
    assert "Local Mode only" in final.reason


def test_approve_without_master_switch_stays_local():
    # User approves, but IRA_ALLOW_EXTERNAL_API is false -> config forbids external.
    d = _hard(env={})
    final = apply_consent(d, approved=True, env={})
    assert final.provider == "local"
    assert final.requires_api_consent is False
    assert "disabled by config" in final.reason


def test_approve_with_master_switch_goes_external():
    env = {
        "IRA_ALLOW_EXTERNAL_API": "true",
        "IRA_EXTERNAL_API_PROVIDER": "anthropic",
        "IRA_EXTERNAL_API_MODEL": "claude-frontier",
    }
    d = _hard(env=env)
    final = apply_consent(d, approved=True, env=env)
    assert final.provider == "external"
    assert final.selected_model == "claude-frontier"
    assert final.estimated_cost_level == "high"
    # The local model is retained as a safety net.
    assert final.fallback_model == "deepseek-r1:14b"


def test_external_never_used_without_calling_apply_consent():
    # The only way to get an external provider is apply_consent(approved=True) with
    # the master switch on. route() alone, even for the hardest task, stays local.
    env = {"IRA_ALLOW_EXTERNAL_API": "true"}
    d = _hard(env=env)
    assert d.provider == "local"


def test_consent_message_is_actionable():
    msg = consent_message()
    assert msg == CONSENT_MESSAGE
    assert "Deep Intelligence Mode" in msg
    assert "Approve" in msg
    assert "Local only" in msg
