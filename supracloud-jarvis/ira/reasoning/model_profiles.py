"""
ira/reasoning/model_profiles.py — IRA's local-first model catalog.

This is the *data* layer for ``ira/reasoning/model_router.py``. It answers one
question: **"which concrete model name belongs to this mode under the active
profile?"** — and nothing else. It owns no network surface and makes no model
calls.

Seven MODES describe the kind of brain a task needs:

  * ``local_fast``       — quick chat, small summaries, low-latency replies
  * ``local_main``       — default high-quality answers, explanations, planning
  * ``local_reasoning``  — deep reasoning, architecture, security, debugging logic
  * ``local_coding``     — code generation/review/refactor, repo work
  * ``local_vision``     — images, screenshots, PDFs-as-images, UI analysis
  * ``memory_embedding`` — RAG / long-term memory retrieval embeddings
  * ``fallback_tiny``    — weak-machine / emergency local response

Three PROFILES bind those modes to real Ollama models:

  * ``balanced_local`` (default) — recommended power/footprint balance
  * ``low_resource``             — lighter stack for weak machines
  * ``strong_local``             — heavier reasoning for capable machines

Resolution order for a mode's model name (first hit wins):

  1. a per-mode environment override (e.g. ``IRA_LOCAL_FAST_MODEL``);
  2. the active profile's value for that mode.

The active profile is ``IRA_MODEL_PROFILE`` (default ``balanced_local``).

Like ``utils/yaml_config.py`` this loads ``config/model_profiles.yaml`` and falls
back to the hardcoded tables below if the file is missing or malformed — so the
catalog is editable without code changes yet always importable with no deps
beyond PyYAML.
"""
from __future__ import annotations

import logging
import os
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Optional

import yaml

logger = logging.getLogger("ira.reasoning.model_profiles")

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
_CONFIG_PATH = _CONFIG_DIR / "model_profiles.yaml"

#: Selected when ``IRA_MODEL_PROFILE`` is unset or unknown.
DEFAULT_PROFILE = "balanced_local"

#: Env var naming the active profile.
PROFILE_ENV_VAR = "IRA_MODEL_PROFILE"


class ModelMode(str, Enum):
    """The kind of brain a task needs. ``str`` mix-in so the value doubles as a
    plain key in YAML/JSON and compares equal to the raw string."""

    LOCAL_FAST = "local_fast"
    LOCAL_MAIN = "local_main"
    LOCAL_REASONING = "local_reasoning"
    LOCAL_CODING = "local_coding"
    LOCAL_VISION = "local_vision"
    MEMORY_EMBEDDING = "memory_embedding"
    FALLBACK_TINY = "fallback_tiny"

    def __str__(self) -> str:  # so f"{mode}" is "local_fast", not "ModelMode.LOCAL_FAST"
        return self.value


# ── Hardcoded fallback catalog (mirrors config/model_profiles.yaml) ────────────
# Used verbatim when the YAML is missing/unreadable, so IRA never loses its model
# map. Keep these in sync with config/model_profiles.yaml.

_DEFAULT_PROFILES: dict[str, dict[str, str]] = {
    "balanced_local": {
        "local_fast": "qwen3:8b",
        "local_main": "qwen3:14b",
        "local_reasoning": "deepseek-r1:14b",
        "local_coding": "qwen3-coder-next",
        "local_vision": "gemma3:12b",
        "memory_embedding": "bge-m3",
        "fallback_tiny": "gemma3n:e4b",
    },
    "low_resource": {
        "local_fast": "qwen3:4b",
        "local_main": "qwen3:8b",
        "local_reasoning": "deepseek-r1:8b",
        "local_coding": "qwen3-coder-next",
        "local_vision": "gemma3:4b",
        "memory_embedding": "nomic-embed-text",
        "fallback_tiny": "gemma3n:e4b",
    },
    "strong_local": {
        "local_fast": "qwen3:8b",
        "local_main": "qwen3:14b",
        "local_reasoning": "deepseek-r1:32b",
        "local_coding": "qwen3-coder-next",
        "local_vision": "gemma3:12b",
        "memory_embedding": "bge-m3",
        "fallback_tiny": "gemma3n:e4b",
    },
}

_DEFAULT_ENV_OVERRIDES: dict[str, str] = {
    "local_fast": "IRA_LOCAL_FAST_MODEL",
    "local_main": "IRA_LOCAL_MAIN_MODEL",
    "local_reasoning": "IRA_LOCAL_REASONING_MODEL",
    "local_coding": "IRA_LOCAL_CODING_MODEL",
    "local_vision": "IRA_LOCAL_VISION_MODEL",
    "memory_embedding": "IRA_EMBEDDING_MODEL",
    "fallback_tiny": "IRA_FALLBACK_TINY_MODEL",
}

_DEFAULT_FALLBACK_CHAINS: dict[str, list[str]] = {
    "local_reasoning": ["local_reasoning", "local_main", "local_fast", "fallback_tiny"],
    "local_coding": ["local_coding", "local_main", "local_fast", "fallback_tiny"],
    "local_vision": ["local_vision", "local_main", "fallback_tiny"],
    "local_main": ["local_main", "local_fast", "fallback_tiny"],
    "local_fast": ["local_fast", "fallback_tiny"],
    "memory_embedding": ["memory_embedding"],
    "fallback_tiny": ["fallback_tiny"],
}

_DEFAULT_EMBEDDING_FALLBACK = "nomic-embed-text"


@lru_cache(maxsize=1)
def _load_config() -> dict:
    """Load ``config/model_profiles.yaml`` once; fall back to hardcoded tables."""
    try:
        with open(_CONFIG_PATH) as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict) or not data.get("profiles"):
            raise ValueError("model_profiles.yaml has no 'profiles' section")
        logger.info("Loaded model profiles from %s", _CONFIG_PATH)
        return data
    except FileNotFoundError:
        logger.warning("model_profiles.yaml not found at %s — using built-in defaults", _CONFIG_PATH)
    except Exception as exc:  # noqa: BLE001 — any malformed YAML degrades to defaults
        logger.error("Failed to load model_profiles.yaml (%s) — using built-in defaults", exc)
    return {
        "default_profile": DEFAULT_PROFILE,
        "profiles": _DEFAULT_PROFILES,
        "env_overrides": _DEFAULT_ENV_OVERRIDES,
        "fallback_chains": _DEFAULT_FALLBACK_CHAINS,
        "embedding_fallback_model": _DEFAULT_EMBEDDING_FALLBACK,
    }


def reload_config() -> None:
    """Drop the cached config so the next read re-parses the YAML (tests/hot-edits)."""
    _load_config.cache_clear()


# ── Public read API ────────────────────────────────────────────────────────────

def list_profiles() -> list[str]:
    """Names of all defined profiles."""
    return sorted(_load_config().get("profiles", {}).keys())


def default_profile_name() -> str:
    """The profile used when none is requested (YAML ``default_profile``)."""
    return _load_config().get("default_profile", DEFAULT_PROFILE)


def active_profile_name(env: Optional[Mapping[str, str]] = None) -> str:
    """Resolve the active profile from ``IRA_MODEL_PROFILE``.

    An unset or unknown value degrades to :func:`default_profile_name` (we never
    raise here — a typo in an env var must not break IRA's startup).
    """
    env = os.environ if env is None else env
    requested = (env.get(PROFILE_ENV_VAR) or "").strip()
    profiles = _load_config().get("profiles", {})
    if requested and requested in profiles:
        return requested
    if requested:
        logger.warning(
            "Unknown %s=%r — falling back to %r", PROFILE_ENV_VAR, requested, default_profile_name()
        )
    return default_profile_name()


def get_profile(name: Optional[str] = None, env: Optional[Mapping[str, str]] = None) -> dict[ModelMode, str]:
    """Return the mode→model map for ``name`` (or the active profile).

    Env overrides are NOT applied here — this is the raw profile. Use
    :func:`model_for` to get the effective, override-aware model name.
    """
    cfg = _load_config()
    profiles = cfg.get("profiles", {})
    resolved = name or active_profile_name(env)
    if resolved not in profiles:
        raise KeyError(
            f"Unknown model profile {resolved!r}. Known profiles: {', '.join(sorted(profiles))}."
        )
    raw = profiles[resolved]
    return {mode: raw[mode.value] for mode in ModelMode if mode.value in raw}


def _coerce_mode(mode: ModelMode | str) -> ModelMode:
    return mode if isinstance(mode, ModelMode) else ModelMode(mode)


def env_var_for(mode: ModelMode | str) -> Optional[str]:
    """The override env var name for a mode (e.g. ``IRA_LOCAL_FAST_MODEL``)."""
    mode = _coerce_mode(mode)
    overrides = _load_config().get("env_overrides", _DEFAULT_ENV_OVERRIDES)
    return overrides.get(mode.value)


def model_for(
    mode: ModelMode | str,
    profile: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> str:
    """Effective model name for ``mode`` — env override first, then the profile.

    Raises ``KeyError`` if the mode is absent from the resolved profile (a
    misconfigured YAML), so callers see the problem instead of a silent empty
    model name.
    """
    mode = _coerce_mode(mode)
    env = os.environ if env is None else env

    var = env_var_for(mode)
    if var:
        override = (env.get(var) or "").strip()
        if override:
            return override

    profile_map = get_profile(profile, env)
    if mode not in profile_map:
        raise KeyError(
            f"Mode {mode.value!r} missing from profile {(profile or active_profile_name(env))!r}."
        )
    return profile_map[mode]


def fallback_chain(mode: ModelMode | str) -> list[ModelMode]:
    """Ordered local fallback modes for ``mode``, starting with the mode itself.

    Never includes an external API — degradation stays local. Unknown modes
    degrade to ``[mode, fallback_tiny]`` so callers always get a terminal step.
    """
    mode = _coerce_mode(mode)
    chains = _load_config().get("fallback_chains", _DEFAULT_FALLBACK_CHAINS)
    raw = chains.get(mode.value)
    if not raw:
        return [mode, ModelMode.FALLBACK_TINY]
    out: list[ModelMode] = []
    for name in raw:
        try:
            out.append(ModelMode(name))
        except ValueError:
            logger.warning("Ignoring unknown mode %r in fallback chain for %s", name, mode.value)
    if not out:
        out = [mode, ModelMode.FALLBACK_TINY]
    return out


def embedding_fallback_model() -> str:
    """Lighter embedding model used when the profile's embedding model is missing."""
    return _load_config().get("embedding_fallback_model", _DEFAULT_EMBEDDING_FALLBACK)


__all__ = [
    "ModelMode",
    "DEFAULT_PROFILE",
    "PROFILE_ENV_VAR",
    "list_profiles",
    "default_profile_name",
    "active_profile_name",
    "get_profile",
    "model_for",
    "env_var_for",
    "fallback_chain",
    "embedding_fallback_model",
    "reload_config",
]
