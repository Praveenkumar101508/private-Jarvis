"""
ira/reasoning/base.py — the typed seam that makes IRA's reasoning engine optional.

Today IRA reaches an LLM through two concrete surfaces:

  * native  — ``utils.llm.chat_complete(messages, use_deep=…, temperature=…,
              max_tokens=…)`` (the LangGraph specialist agents, the realtime brain).
  * Cortex  — ``cortex_bridge.CortexBridge.ask(prompt, system=…, reasoning_only=…)``
              (the ``ira/skills/<name>/`` personas and the ``subagents`` deliberation).

Both collapse to the same operation: *given a trusted system instruction and a
user prompt, return the completion text*. ``ReasoningBackend`` is that single
method, so "which engine answers" becomes one typed, validated choice instead of
an ``IRA_USE_CORTEX`` env read scattered across call sites.

DESIGN RULES
  * No invented methods — ``complete()`` mirrors the parameters the two real
    surfaces already accept (``use_deep``, ``temperature``, ``max_tokens``,
    ``reasoning_only``; ``json_mode`` is advisory, as in the realtime brain).
  * Per-backend secret validation: ``validate()`` checks ONLY the secrets the
    selected backend needs, so the local-first default starts with no keys.
  * This module is import-light (pure stdlib); every backend imports its heavy
    deps lazily, so ``MockBackend`` is usable with nothing installed.
"""
from __future__ import annotations

import abc
from typing import Optional


class ReasoningBackendError(RuntimeError):
    """Raised when a selected backend is misconfigured (missing secret/binary)."""


class ReasoningBackend(abc.ABC):
    """One reasoning engine behind a single typed call.

    Implementations wrap an existing IRA seam; they never grow a network surface
    of their own beyond what that seam already has.
    """

    #: short, stable identifier used by selection + logging (e.g. "ollama").
    name: str = "base"

    @abc.abstractmethod
    async def complete(
        self,
        system: str,
        prompt: str,
        *,
        use_deep: bool = False,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
        reasoning_only: bool = False,
    ) -> str:
        """Return the completion text for (trusted ``system``, user ``prompt``).

        ``reasoning_only`` requests a no-tools call (IRA runs real tools itself and
        passes results in as context); backends that have no tools ignore it.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def validate(self) -> None:
        """Raise :class:`ReasoningBackendError` if THIS backend's required secrets
        or runtime prerequisites are missing. Backends with no secret are no-ops."""
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"<ReasoningBackend {self.name!r}>"
