"""
YAML-based configuration loader for IRA routing and agent settings.
Falls back to hardcoded defaults if YAML files are missing.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import yaml

logger = logging.getLogger("ira.config")

_CONFIG_DIR = Path(__file__).parent.parent / "config"


@lru_cache(maxsize=1)
def load_routing_config() -> dict:
    """Load routing.yaml — cached after first load."""
    config_path = _CONFIG_DIR / "routing.yaml"
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
        logger.info(f"Loaded routing config from {config_path}")
        return config
    except FileNotFoundError:
        logger.warning(f"routing.yaml not found at {config_path} — using hardcoded defaults")
        return {}
    except Exception as e:
        logger.error(f"Failed to load routing.yaml: {e} — using hardcoded defaults")
        return {}


def get_fast_keywords() -> frozenset[str]:
    return frozenset(load_routing_config().get("fast_keywords", []))


def get_deep_keywords() -> frozenset[str]:
    return frozenset(load_routing_config().get("deep_keywords", []))


def get_reasoning_keywords() -> frozenset[str]:
    return frozenset(load_routing_config().get("reasoning_keywords", []))


def get_restricted_keywords() -> frozenset[str]:
    return frozenset(load_routing_config().get("restricted_keywords", []))


def get_agent_rules() -> list[tuple[frozenset[str], str]]:
    rules_dict = load_routing_config().get("agent_rules", {})
    return [(frozenset(kws), agent) for agent, kws in rules_dict.items()]
