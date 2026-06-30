"""Phase 3 — local fallback when the preferred model is missing.

Proves the router degrades to the next available LOCAL model (never an external
API), per the rules:
  * missing model -> next available local model;
  * no deep model -> local_main; main missing -> local_fast; else -> fallback_tiny;
  * an unreachable probe keeps the preferred model (don't override on failure);
  * embeddings degrade to the lighter embedding model, not a chat model.
"""
import pytest

from reasoning.model_availability import ModelAvailability
from reasoning.model_profiles import ModelMode, reload_config
from reasoning.model_router import resolve_model, route

ENV = {}


@pytest.fixture(autouse=True)
def _fresh():
    reload_config()
    yield
    reload_config()


def installed(*names):
    return ModelAvailability(reachable=True, models=frozenset(names), source="test")


UNREACHABLE = ModelAvailability(reachable=False, models=frozenset(), source="test")


def test_missing_reasoning_falls_back_to_main():
    avail = installed("qwen3:14b", "qwen3:8b", "gemma3n:e4b")  # no deepseek
    used, model, fb = resolve_model(ModelMode.LOCAL_REASONING, env=ENV, availability=avail)
    assert used == ModelMode.LOCAL_MAIN
    assert model == "qwen3:14b"
    assert fb == "qwen3:8b"


def test_missing_main_falls_back_to_fast():
    avail = installed("qwen3:8b", "gemma3n:e4b")  # no qwen3:14b
    used, model, _ = resolve_model(ModelMode.LOCAL_MAIN, env=ENV, availability=avail)
    assert used == ModelMode.LOCAL_FAST
    assert model == "qwen3:8b"


def test_only_tiny_available_lands_on_tiny():
    avail = installed("gemma3n:e4b")
    used, model, fb = resolve_model(ModelMode.LOCAL_REASONING, env=ENV, availability=avail)
    assert used == ModelMode.FALLBACK_TINY
    assert model == "gemma3n:e4b"
    assert fb is None


def test_nothing_installed_still_returns_terminal_tiny():
    avail = installed()  # reachable but empty
    used, model, _ = resolve_model(ModelMode.LOCAL_MAIN, env=ENV, availability=avail)
    assert used == ModelMode.FALLBACK_TINY
    assert model == "gemma3n:e4b"


def test_unreachable_probe_keeps_preferred_model():
    used, model, _ = resolve_model(ModelMode.LOCAL_REASONING, env=ENV, availability=UNREACHABLE)
    assert used == ModelMode.LOCAL_REASONING
    assert model == "deepseek-r1:14b"


def test_embedding_falls_back_to_lighter_embedding():
    avail = installed("qwen3:8b")  # bge-m3 not installed
    used, model, fb = resolve_model(ModelMode.MEMORY_EMBEDDING, env=ENV, availability=avail)
    assert used == ModelMode.MEMORY_EMBEDDING
    assert model == "nomic-embed-text"        # NOT a chat model
    assert fb is None


def test_embedding_present_is_used_directly():
    avail = installed("bge-m3")
    used, model, fb = resolve_model(ModelMode.MEMORY_EMBEDDING, env=ENV, availability=avail)
    assert model == "bge-m3"
    assert fb == "nomic-embed-text"


def test_route_reports_fallback_in_reason():
    avail = installed("qwen3:14b", "qwen3:8b", "gemma3n:e4b")  # no coder
    d = route("refactor this module", env=ENV, availability=avail)
    assert d.selected_mode == ModelMode.LOCAL_MAIN     # coding -> main fallback
    assert "fell back" in d.reason
    assert d.allow_local_fallback is True


def test_fallback_never_selects_external():
    # Even with nothing installed, the fallback path stays local.
    d = route("do a very deep security audit", env=ENV, availability=installed())
    assert d.provider == "local"
