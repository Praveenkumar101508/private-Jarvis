"""Phase 3 — task -> model-mode routing.

Proves the router sends each kind of task to the right mode (using the default
``balanced_local`` profile), and that every route is local-first.
"""
import pytest

from reasoning.model_availability import ModelAvailability
from reasoning.model_profiles import ModelMode, reload_config
from reasoning.model_router import route

# Probe is "unreachable" -> available_or_unknown is optimistic, so the PREFERRED
# model is always chosen and routing isn't masked by what happens to be installed.
UNKNOWN = ModelAvailability(reachable=False, models=frozenset(), source="test")
ENV = {}  # no overrides -> default balanced_local profile


@pytest.fixture(autouse=True)
def _fresh():
    reload_config()
    yield
    reload_config()


def _route(prompt, **kw):
    return route(prompt, env=ENV, availability=UNKNOWN, **kw)


def test_simple_chat_routes_to_local_fast():
    d = _route("hi")
    assert d.selected_mode == ModelMode.LOCAL_FAST
    assert d.selected_model == "qwen3:8b"


def test_short_request_routes_to_local_fast():
    d = _route("what time is it")
    assert d.selected_mode == ModelMode.LOCAL_FAST


def test_normal_answer_routes_to_local_main():
    d = _route("Explain how photosynthesis works in plants and why it matters")
    assert d.selected_mode == ModelMode.LOCAL_MAIN
    assert d.selected_model == "qwen3:14b"


def test_coding_routes_to_local_coding():
    d = _route("debug this python function that throws an exception")
    assert d.selected_mode == ModelMode.LOCAL_CODING
    assert d.selected_model == "qwen3-coder-next"


def test_reasoning_keywords_route_to_local_reasoning():
    d = _route("design a scalable architecture for a multi-tenant system")
    assert d.selected_mode == ModelMode.LOCAL_REASONING
    assert d.selected_model == "deepseek-r1:14b"


def test_think_mode_forces_local_reasoning():
    d = _route("tell me about cats", think_mode=True)
    assert d.selected_mode == ModelMode.LOCAL_REASONING


def test_image_input_routes_to_local_vision():
    d = _route("what's in this screenshot?", has_image=True)
    assert d.selected_mode == ModelMode.LOCAL_VISION
    assert d.selected_model == "gemma3:12b"


def test_memory_search_routes_to_embedding():
    d = _route("anything", is_memory_search=True)
    assert d.selected_mode == ModelMode.MEMORY_EMBEDDING
    assert d.selected_model == "bge-m3"


def test_memory_keywords_route_to_embedding():
    d = _route("search my memory for the budget notes")
    assert d.selected_mode == ModelMode.MEMORY_EMBEDDING


def test_explicit_task_type_overrides_text():
    d = _route("hi", task_type="architecture")
    assert d.selected_mode == ModelMode.LOCAL_REASONING


def test_default_is_local_first_and_provider_local():
    d = _route("Explain the history of the Roman empire briefly please")
    assert d.privacy_level == "local_first"
    assert d.provider == "local"
    assert d.is_local
    assert d.estimated_cost_level == "none"


def test_low_resource_profile_changes_models():
    env = {"IRA_MODEL_PROFILE": "low_resource"}
    d = route("hi", env=env, availability=UNKNOWN)
    assert d.selected_mode == ModelMode.LOCAL_FAST
    assert d.selected_model == "qwen3:4b"


def test_very_hard_task_offers_consent_but_stays_local():
    d = _route("do a very deep architecture and security refactor of the whole system")
    assert d.selected_mode == ModelMode.LOCAL_REASONING
    assert d.requires_api_consent is True
    assert d.provider == "local"            # still local until approved
    assert d.estimated_cost_level == "none"
