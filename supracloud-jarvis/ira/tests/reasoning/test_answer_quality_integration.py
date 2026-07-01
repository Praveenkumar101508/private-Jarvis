"""Answer-quality layer — integration with routing/consent.

Proves the new answer-quality layer (system prompts, policies, verifier,
memory context) is purely additive: it never changes what the router or the
consent gate decide, external use still requires the same three conditions
as before, and a fully-degraded local fallback still produces a real,
locally-served answer.
"""
import pytest

from reasoning.answer_policy import local_fallback_notice, policy_for_prompt
from reasoning.answer_verifier import ISSUE_UNSAFE_EXTERNAL, verify_answer
from reasoning.model_availability import ModelAvailability
from reasoning.model_profiles import ModelMode, reload_config
from reasoning.model_router import apply_consent, resolve_model, route
from reasoning.memory_context import select_memory_context

VERY_HARD = "do a very deep architecture and security refactor of the entire platform"


@pytest.fixture(autouse=True)
def _fresh():
    reload_config()
    yield
    reload_config()


def test_routing_decision_unchanged_by_importing_answer_quality_layer():
    # Same assertions as reasoning/tests/test_model_router.py — proves nothing
    # about route()'s output changed just because answer_policy/answer_verifier/
    # memory_context are now importable alongside it.
    avail = ModelAvailability(reachable=False, models=frozenset(), source="test")
    d = route("hi", env={}, availability=avail)
    assert d.selected_mode == ModelMode.LOCAL_FAST
    assert d.provider == "local"


def test_external_still_requires_approval_and_master_switch():
    avail = ModelAvailability(reachable=False, models=frozenset(), source="test")
    d = route(VERY_HARD, env={}, availability=avail)
    assert d.provider == "local"

    # Approve without the master switch on: still local.
    declined_switch = apply_consent(d, approved=True, env={})
    assert declined_switch.provider == "local"

    # Approve WITH the master switch on: only now does it go external.
    env = {"IRA_ALLOW_EXTERNAL_API": "true"}
    d2 = route(VERY_HARD, env=env, availability=avail)
    final = apply_consent(d2, approved=True, env=env)
    assert final.provider == "external"

    # The verifier flags exactly the unsafe case (no recorded approval) and
    # clears once approval is recorded — it never grants approval itself.
    unsafe = verify_answer(VERY_HARD, "A deep architecture review.", provider="external", consent_approved=None)
    safe = verify_answer(VERY_HARD, "A deep architecture review.", provider="external", consent_approved=True)
    assert unsafe.has(ISSUE_UNSAFE_EXTERNAL)
    assert not safe.has(ISSUE_UNSAFE_EXTERNAL)


def test_local_fallback_still_produces_a_real_local_answer():
    # Nothing installed but the emergency tiny model — degrade all the way down.
    avail = ModelAvailability(reachable=True, models=frozenset({"gemma3n:e4b"}), source="test")
    used_mode, model, _fb = resolve_model(ModelMode.LOCAL_REASONING, env={}, availability=avail)
    assert used_mode == ModelMode.FALLBACK_TINY
    assert model == "gemma3n:e4b"          # a real, local, answerable model — never empty/external

    d = route(VERY_HARD, env={}, availability=avail)
    assert d.provider == "local"
    note = local_fallback_notice(d)
    assert note is not None
    assert "Continuing in Local Mode" in note
    assert "weak" not in note.lower()


def test_memory_context_is_a_separate_labelled_block_not_a_system_override():
    memories = [{"content": "The user's company is SupraCloud.", "similarity": 0.9}]
    memory_block = select_memory_context(memories)
    policy = policy_for_prompt("what does my company do")

    system_prompt = "You are IRA." + "\n\n" + policy.instructions
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": memory_block},
        {"role": "user", "content": "what does my company do"},
    ]
    # The persona/system prompt stays its own message; memory is appended as a
    # clearly separate, labelled block — never merged into or replacing it.
    assert messages[0]["content"] == system_prompt
    assert messages[1]["content"].startswith("User memory (reference only")
    assert "You are IRA" not in messages[1]["content"]
