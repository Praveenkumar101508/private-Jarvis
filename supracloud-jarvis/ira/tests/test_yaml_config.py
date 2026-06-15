"""Unit tests for utils/yaml_config.py — YAML-based routing configuration."""
import pytest
from utils.yaml_config import (
    load_routing_config,
    get_fast_keywords,
    get_deep_keywords,
    get_reasoning_keywords,
    get_restricted_keywords,
    get_agent_rules,
)


def setup_module():
    load_routing_config.cache_clear()


def test_routing_config_loads():
    cfg = load_routing_config()
    assert isinstance(cfg, dict)
    assert "fast_keywords" in cfg
    assert "deep_keywords" in cfg
    assert "restricted_keywords" in cfg
    assert "agent_rules" in cfg


def test_fast_keywords_nonempty():
    kw = get_fast_keywords()
    assert len(kw) > 0


def test_deep_keywords_nonempty():
    kw = get_deep_keywords()
    assert len(kw) > 0


def test_reasoning_keywords_nonempty():
    kw = get_reasoning_keywords()
    assert len(kw) > 0


def test_restricted_keywords_nonempty():
    kw = get_restricted_keywords()
    assert len(kw) > 0


def test_agent_rules_is_list_of_tuples():
    rules = get_agent_rules()
    assert isinstance(rules, list)
    assert len(rules) > 0
    for keywords, agent_name in rules:
        assert isinstance(keywords, frozenset)
        assert isinstance(agent_name, str)
        assert len(keywords) > 0


def test_required_agents_present():
    agents = {agent for _, agent in get_agent_rules()}
    for required in ("security", "researcher", "executor"):
        assert required in agents, f"Agent '{required}' missing from routing rules"


def test_restricted_keywords_contains_sensitive_terms():
    # These phrases are explicitly listed in routing.yaml
    kw = get_restricted_keywords()
    sensitive = {"credentials", "private key", "api key", ".env", "show logs"}
    assert any(term in kw for term in sensitive), (
        f"Restricted keywords should include at least one of {sensitive}"
    )


def test_fast_keywords_are_strings():
    for kw in get_fast_keywords():
        assert isinstance(kw, str)


def test_no_duplicate_keywords_across_fast_and_deep():
    fast = get_fast_keywords()
    deep = get_deep_keywords()
    overlap = fast & deep
    assert len(overlap) == 0, f"Keyword overlap between fast and deep tiers: {overlap}"
