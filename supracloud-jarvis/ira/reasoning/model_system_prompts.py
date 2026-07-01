"""
ira/reasoning/model_system_prompts.py — model-tier system prompt catalog.

Data layer answering: "what short system-prompt fragment matches THIS model
tier's role?" One prompt per :class:`~reasoning.model_profiles.ModelMode`,
loaded from ``config/model_system_prompts.yaml`` with a hardcoded fallback so
IRA never loses tier guidance if the YAML is missing or malformed.

These fragments are meant to be APPENDED to a skill's persona system prompt
(see ``agents/*.py`` and ``api/routes/chat.py``) — they shape *how* the
selected model tier should write (concise vs careful vs tests-first), not
*what* domain it's answering in. They make no model calls and own no network
surface, same as ``model_profiles.py``.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import yaml

from reasoning.model_profiles import ModelMode

logger = logging.getLogger("ira.reasoning.model_system_prompts")

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
_CONFIG_PATH = _CONFIG_DIR / "model_system_prompts.yaml"

# ── Hardcoded fallback catalog (mirrors config/model_system_prompts.yaml) ──
# Used verbatim when the YAML is missing/unreadable, so IRA never loses tier
# guidance. Keep these in sync with the YAML file.

_DEFAULT_PROMPTS: dict[str, str] = {
    "local_fast": (
        "You are running on IRA's fast local tier. Be concise and direct: "
        "answer in as few words as truthfully possible, skip preamble, and "
        "never pad a quick answer with unnecessary structure. Low latency "
        "matters more than depth here — if the question needs real depth, "
        "say so briefly rather than guessing."
    ),
    "local_main": (
        "You are running on IRA's main local tier — the default "
        "high-quality brain. Be helpful, clear, and practical: structure "
        "longer answers with short headers or lists only when structure "
        "genuinely helps, lead with the answer, then explain. Prefer "
        "concrete, actionable detail over generic advice."
    ),
    "local_reasoning": (
        "You are running on IRA's reasoning tier for hard problems: "
        "architecture, security, multi-step planning, debugging logic. Work "
        "carefully — check your assumptions before committing to an answer, "
        "and consider at least one alternative before you settle on a "
        'recommendation. Give a clear, step-by-step FINAL reasoning trail in '
        'your answer (the "why", not just the "what"), but do not dump raw '
        "scratch-pad chain-of-thought — synthesize it into a clean "
        "explanation."
    ),
    "local_coding": (
        "You are running on IRA's coding tier. Be precise: read the "
        "existing code's conventions before proposing changes, and never "
        "suggest something that would break working code without saying "
        "so. Default to tests-first — propose or reference a "
        "test/verification step for any nontrivial change. Explain changes "
        "file-by-file when more than one file is touched, and explicitly "
        "flag risks (breaking changes, missing edge cases, migrations)."
    ),
    "local_vision": (
        "You are running on IRA's vision tier. Describe what is actually "
        "visible in the image first, and clearly separate that observation "
        "from any inference or guess you make beyond it. Ask a clarifying "
        "question only when the image is genuinely ambiguous for the "
        "user's request — do not ask by default."
    ),
    "fallback_tiny": (
        "You are running on IRA's small emergency local model because a "
        'larger model is unavailable right now. Never say you are "weak" '
        'or apologize for your size — if it\'s relevant, simply note '
        '"Continuing in Local Mode" and move on. Give the best, most '
        "honest answer you can with what you have: be simple, direct, and "
        "concise, and do not overclaim capability or certainty you don't "
        "have. If the task genuinely needs deeper reasoning than you can "
        "provide, say so plainly and let IRA offer Deep Intelligence Mode "
        "— don't pretend to be more capable than you are."
    ),
}


@lru_cache(maxsize=1)
def _load_prompts() -> dict[str, str]:
    """Load ``config/model_system_prompts.yaml`` once; fall back to hardcoded copies."""
    try:
        with open(_CONFIG_PATH) as fh:
            data = yaml.safe_load(fh) or {}
        prompts = data.get("prompts") if isinstance(data, dict) else None
        if not isinstance(prompts, dict) or not prompts:
            raise ValueError("model_system_prompts.yaml has no 'prompts' section")
        logger.info("Loaded model system prompts from %s", _CONFIG_PATH)
        # Merge over the defaults so a partial/edited file never drops a mode.
        merged = dict(_DEFAULT_PROMPTS)
        merged.update({str(k): str(v).strip() for k, v in prompts.items() if str(v).strip()})
        return merged
    except FileNotFoundError:
        logger.warning(
            "model_system_prompts.yaml not found at %s — using built-in defaults", _CONFIG_PATH
        )
    except Exception as exc:  # noqa: BLE001 — malformed YAML degrades to defaults
        logger.error("Failed to load model_system_prompts.yaml (%s) — using built-in defaults", exc)
    return dict(_DEFAULT_PROMPTS)


def reload_config() -> None:
    """Drop the cached prompts so the next read re-parses the YAML (tests/hot-edits)."""
    _load_prompts.cache_clear()


def system_prompt_for(mode: "ModelMode | str") -> str:
    """Return the tier-appropriate system-prompt fragment for ``mode``.

    Never raises: an unknown mode degrades to the ``local_main`` fragment so
    a caller always gets *something* reasonable back.
    """
    key = mode.value if isinstance(mode, ModelMode) else str(mode)
    prompts = _load_prompts()
    return prompts.get(key) or prompts.get(ModelMode.LOCAL_MAIN.value, "")


__all__ = ["system_prompt_for", "reload_config"]
