"""
ira/reasoning — the reasoning-backend seam (V1·Phase 2).

``get_reasoning_backend()`` is the single place that turns a name into a validated
backend. Selection order:

  1. an explicit ``name`` argument (tests, callers that already decided);
  2. the ``IRA_LLM_BACKEND`` env var;
  3. ``config.llm_backend`` (so existing ollama/vllm behaviour is preserved).

Only the SELECTED backend is validated — the local-first default ("ollama") and
"mock" start with no keys; "vllm" and "cortex" refuse to start when their secret /
binary is missing. This makes "Cortex optional" a structural guarantee, not a
default env value that a stray export could flip.
"""
from __future__ import annotations

import os
from typing import Optional

from reasoning.base import ReasoningBackend, ReasoningBackendError
from reasoning.backends import CortexBackend, LocalLLMBackend, MockBackend

_LOCAL_KINDS = {"ollama", "vllm"}


def available_backends() -> tuple[str, ...]:
    return ("ollama", "vllm", "cortex", "mock")


def _resolve_name(name: Optional[str]) -> str:
    if name:
        return name.strip().lower()
    env = os.getenv("IRA_LLM_BACKEND", "").strip().lower()
    if env:
        return env
    # Fall back to the existing config switch so default behaviour is unchanged.
    try:
        from config import get_settings

        return get_settings().llm_backend.strip().lower()
    except Exception:  # noqa: BLE001 - config may be unset in a bare/mock context
        return "ollama"


def make_backend(name: Optional[str] = None) -> ReasoningBackend:
    """Construct a backend by name WITHOUT validating its secrets."""
    resolved = _resolve_name(name)
    if resolved in _LOCAL_KINDS:
        return LocalLLMBackend(kind=resolved)
    if resolved == "cortex":
        return CortexBackend()
    if resolved == "mock":
        return MockBackend()
    raise ReasoningBackendError(
        f"Unknown reasoning backend {resolved!r}. "
        f"Choose one of: {', '.join(available_backends())}."
    )


def get_reasoning_backend(name: Optional[str] = None, *, validate: bool = True) -> ReasoningBackend:
    """Return the selected reasoning backend, validating its secrets by default.

    Raises :class:`ReasoningBackendError` if the selected backend's required secret
    (vLLM key) or prerequisite (cortex binary) is missing. Other backends' secrets
    are never consulted.
    """
    backend = make_backend(name)
    if validate:
        backend.validate()
    return backend


__all__ = [
    "ReasoningBackend",
    "ReasoningBackendError",
    "LocalLLMBackend",
    "CortexBackend",
    "MockBackend",
    "make_backend",
    "get_reasoning_backend",
    "available_backends",
]
