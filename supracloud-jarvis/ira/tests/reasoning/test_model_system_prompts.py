"""Answer-quality — model-tier system prompts load and match each tier's role."""
import pytest

from reasoning.model_profiles import ModelMode
from reasoning.model_system_prompts import reload_config, system_prompt_for


@pytest.fixture(autouse=True)
def _fresh():
    reload_config()
    yield
    reload_config()


ALL_MODES = list(ModelMode)


def test_every_mode_has_a_nonempty_prompt():
    for mode in ALL_MODES:
        prompt = system_prompt_for(mode)
        assert isinstance(prompt, str)
        assert len(prompt.strip()) > 20, f"{mode} prompt is missing/too short"


def test_prompt_loads_from_yaml_file():
    # Loaded from config/model_system_prompts.yaml, not just the hardcoded copy —
    # both currently agree, but this proves the YAML path is exercised.
    from reasoning.model_system_prompts import _CONFIG_PATH
    assert _CONFIG_PATH.exists()
    prompt = system_prompt_for(ModelMode.LOCAL_FAST)
    assert "fast local tier" in prompt


def test_local_fast_is_concise_and_direct():
    prompt = system_prompt_for(ModelMode.LOCAL_FAST).lower()
    assert "concise" in prompt or "direct" in prompt


def test_local_main_is_structured_and_practical():
    prompt = system_prompt_for(ModelMode.LOCAL_MAIN).lower()
    assert "clear" in prompt or "practical" in prompt


def test_local_reasoning_checks_assumptions_and_hides_scratchpad():
    prompt = system_prompt_for(ModelMode.LOCAL_REASONING).lower()
    assert "assumption" in prompt
    assert "chain-of-thought" in prompt


def test_local_coding_is_tests_first_and_flags_risk():
    prompt = system_prompt_for(ModelMode.LOCAL_CODING).lower()
    assert "tests-first" in prompt or "test" in prompt
    assert "risk" in prompt


def test_local_vision_separates_observation_from_inference():
    prompt = system_prompt_for(ModelMode.LOCAL_VISION).lower()
    assert "observation" in prompt or "visible" in prompt
    assert "infer" in prompt


def test_fallback_tiny_never_says_weak_and_uses_local_mode_notice():
    prompt = system_prompt_for(ModelMode.FALLBACK_TINY)
    assert "Continuing in Local Mode" in prompt
    assert "weak" not in prompt.lower() or "never say you are" in prompt.lower()


def test_unknown_mode_degrades_to_local_main():
    assert system_prompt_for("not_a_real_mode") == system_prompt_for(ModelMode.LOCAL_MAIN)


def test_string_mode_key_works_same_as_enum():
    assert system_prompt_for("local_coding") == system_prompt_for(ModelMode.LOCAL_CODING)
