"""Phase 1 — model profile catalog.

Proves the data layer behind IRA's model router:
  * the default profile is ``balanced_local`` and binds the documented models;
  * ``low_resource`` and ``strong_local`` exist with the documented models;
  * ``IRA_MODEL_PROFILE`` selects the active profile; unknown values degrade;
  * per-mode env overrides (e.g. ``IRA_LOCAL_FAST_MODEL``) win over the profile;
  * every profile defines all seven modes;
  * fallback chains start with the mode and end at ``fallback_tiny`` (local-only).
"""
import pytest

from reasoning.model_profiles import (
    ModelMode,
    active_profile_name,
    default_profile_name,
    embedding_fallback_model,
    fallback_chain,
    get_profile,
    list_profiles,
    model_for,
    reload_config,
)


@pytest.fixture(autouse=True)
def _fresh_config():
    """Each test reads the YAML fresh (the loader is lru_cache'd)."""
    reload_config()
    yield
    reload_config()


def test_default_profile_is_balanced_local():
    assert default_profile_name() == "balanced_local"
    # No env set → active profile is the default.
    assert active_profile_name(env={}) == "balanced_local"


def test_all_three_profiles_exist():
    assert set(list_profiles()) == {"balanced_local", "low_resource", "strong_local"}


def test_every_profile_defines_all_seven_modes():
    for name in list_profiles():
        profile = get_profile(name, env={})
        assert set(profile.keys()) == set(ModelMode), f"{name} is missing modes"
        assert all(profile[m] for m in ModelMode), f"{name} has an empty model name"


def test_balanced_local_models():
    p = get_profile("balanced_local", env={})
    assert p[ModelMode.LOCAL_FAST] == "qwen3:8b"
    assert p[ModelMode.LOCAL_MAIN] == "qwen3:14b"
    assert p[ModelMode.LOCAL_REASONING] == "deepseek-r1:14b"
    assert p[ModelMode.LOCAL_CODING] == "qwen3-coder-next"
    assert p[ModelMode.LOCAL_VISION] == "gemma3:12b"
    assert p[ModelMode.MEMORY_EMBEDDING] == "bge-m3"
    assert p[ModelMode.FALLBACK_TINY] == "gemma3n:e4b"


def test_low_resource_models():
    p = get_profile("low_resource", env={})
    assert p[ModelMode.LOCAL_FAST] == "qwen3:4b"
    assert p[ModelMode.LOCAL_MAIN] == "qwen3:8b"
    assert p[ModelMode.LOCAL_REASONING] == "deepseek-r1:8b"
    assert p[ModelMode.LOCAL_VISION] == "gemma3:4b"
    assert p[ModelMode.MEMORY_EMBEDDING] == "nomic-embed-text"


def test_strong_local_uses_bigger_reasoning():
    p = get_profile("strong_local", env={})
    assert p[ModelMode.LOCAL_REASONING] == "deepseek-r1:32b"


def test_profile_env_var_selects_active_profile():
    assert active_profile_name(env={"IRA_MODEL_PROFILE": "low_resource"}) == "low_resource"
    assert active_profile_name(env={"IRA_MODEL_PROFILE": "strong_local"}) == "strong_local"


def test_unknown_profile_env_degrades_to_default():
    assert active_profile_name(env={"IRA_MODEL_PROFILE": "does_not_exist"}) == "balanced_local"
    assert active_profile_name(env={"IRA_MODEL_PROFILE": "  "}) == "balanced_local"


def test_model_for_uses_active_profile():
    # local_fast under the (default) balanced profile.
    assert model_for(ModelMode.LOCAL_FAST, env={}) == "qwen3:8b"
    # selecting low_resource via env changes the resolved model.
    env = {"IRA_MODEL_PROFILE": "low_resource"}
    assert model_for(ModelMode.LOCAL_FAST, env=env) == "qwen3:4b"


def test_env_override_wins_over_profile():
    env = {"IRA_LOCAL_FAST_MODEL": "my-custom:latest"}
    assert model_for(ModelMode.LOCAL_FAST, env=env) == "my-custom:latest"
    # blank override is ignored (falls back to the profile value).
    assert model_for(ModelMode.LOCAL_FAST, env={"IRA_LOCAL_FAST_MODEL": "  "}) == "qwen3:8b"


def test_env_override_string_mode_accepted():
    # callers may pass the raw string instead of the enum.
    assert model_for("local_main", env={}) == "qwen3:14b"


def test_get_profile_unknown_raises():
    with pytest.raises(KeyError):
        get_profile("nope", env={})


def test_fallback_chain_reasoning_degrades_locally():
    chain = fallback_chain(ModelMode.LOCAL_REASONING)
    assert chain[0] == ModelMode.LOCAL_REASONING
    assert chain[-1] == ModelMode.FALLBACK_TINY
    assert ModelMode.LOCAL_MAIN in chain
    assert ModelMode.LOCAL_FAST in chain


def test_fallback_chain_coding_degrades_to_main():
    chain = fallback_chain(ModelMode.LOCAL_CODING)
    assert chain[0] == ModelMode.LOCAL_CODING
    assert ModelMode.LOCAL_MAIN in chain
    assert chain[-1] == ModelMode.FALLBACK_TINY


def test_fallback_chain_tiny_is_terminal():
    assert fallback_chain(ModelMode.FALLBACK_TINY) == [ModelMode.FALLBACK_TINY]


def test_embedding_fallback_is_a_real_embedding_model():
    assert embedding_fallback_model() == "nomic-embed-text"
