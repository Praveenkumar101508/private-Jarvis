"""M2 — the external execution gate.

Proves Deep Intelligence Mode cannot reach the network without (a) an approved
external decision, (b) the IRA_ALLOW_EXTERNAL_API master switch, and (c) an
explicitly registered executor. Local decisions always run locally.
"""
import pytest

from reasoning.model_availability import ModelAvailability
from reasoning.model_profiles import reload_config
from reasoning.model_router import (
    ExternalExecutorNotConfigured,
    apply_consent,
    clear_external_executor,
    register_external_executor,
    route,
    run_decision,
)

UNKNOWN = ModelAvailability(reachable=False, models=frozenset(), source="test")
VERY_HARD = "do a very deep architecture and security refactor of the entire platform"


@pytest.fixture(autouse=True)
def _fresh():
    reload_config()
    clear_external_executor()
    yield
    clear_external_executor()
    reload_config()


def _local_runner(decision):
    return f"local:{decision.selected_model}"


def test_local_decision_runs_locally():
    d = route("hi", env={}, availability=UNKNOWN)
    out = run_decision(d, local_runner=_local_runner, env={})
    assert out.startswith("local:")


def test_external_decision_without_executor_raises():
    env = {"IRA_ALLOW_EXTERNAL_API": "true"}
    d = route(VERY_HARD, env=env, availability=UNKNOWN)
    ext = apply_consent(d, approved=True, env=env)
    assert ext.provider == "external"
    with pytest.raises(ExternalExecutorNotConfigured):
        run_decision(ext, local_runner=_local_runner, env=env)


def test_external_decision_blocked_when_master_switch_off():
    # Even with an executor registered, master switch off blocks execution.
    register_external_executor(lambda d, s, p: "EXTERNAL CALLED")
    env = {"IRA_ALLOW_EXTERNAL_API": "true"}
    d = route(VERY_HARD, env=env, availability=UNKNOWN)
    ext = apply_consent(d, approved=True, env=env)
    # Now run with the master switch OFF.
    with pytest.raises(ExternalExecutorNotConfigured):
        run_decision(ext, local_runner=_local_runner, env={"IRA_ALLOW_EXTERNAL_API": "false"})


def test_external_decision_runs_only_with_executor_and_switch():
    calls = []
    register_external_executor(lambda d, s, p: calls.append(d.selected_model) or "EXTERNAL OK")
    env = {"IRA_ALLOW_EXTERNAL_API": "true", "IRA_EXTERNAL_API_MODEL": "claude-frontier"}
    d = route(VERY_HARD, env=env, availability=UNKNOWN)
    ext = apply_consent(d, approved=True, env=env)
    out = run_decision(ext, local_runner=_local_runner, env=env)
    assert out == "EXTERNAL OK"
    assert calls == ["claude-frontier"]


def test_declined_decision_runs_locally_even_with_executor():
    register_external_executor(lambda d, s, p: "EXTERNAL CALLED")
    env = {"IRA_ALLOW_EXTERNAL_API": "true"}
    d = route(VERY_HARD, env=env, availability=UNKNOWN)
    final = apply_consent(d, approved=False, env=env)  # user said "Local only"
    out = run_decision(final, local_runner=_local_runner, env=env)
    assert out.startswith("local:")
