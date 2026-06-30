"""
ira/reasoning/backends.py — the concrete reasoning backends.

  * LocalLLMBackend — wraps ``utils.llm.chat_complete`` (the native path). One class
    serves both ``ollama`` (default, no key) and ``vllm`` (key-gated) because the
    client choice already lives in ``utils.llm`` / ``config.llm_backend``; the only
    difference here is which secret ``validate()`` insists on.
  * CortexBackend  — wraps ``cortex_bridge.CortexBridge.ask`` (the optional engine).
  * MockBackend    — deterministic, dependency-free; for tests and portable/offline
    bring-up. Needs no keys and never touches the network.

All heavy imports are lazy so importing this module (and using ``MockBackend``)
needs nothing beyond the standard library.
"""
from __future__ import annotations

import asyncio
import shutil
from typing import Optional

from reasoning.base import ReasoningBackend, ReasoningBackendError


class LocalLLMBackend(ReasoningBackend):
    """Native IRA reasoning via ``utils.llm.chat_complete``.

    ``kind`` is "ollama" (local-first default; no secret) or "vllm" (the GPU/Docker
    path; requires ``VLLM_API_KEY``). The actual OpenAI-compatible client is still
    selected inside ``utils.llm`` from ``config.llm_backend`` — this backend does not
    duplicate that routing, it only enforces the matching secret.
    """

    def __init__(self, kind: str = "ollama") -> None:
        self.kind = kind.strip().lower()
        self.name = self.kind

    def validate(self) -> None:
        if self.kind == "vllm":
            from config import get_settings

            if not get_settings().vllm_api_key:
                raise ReasoningBackendError(
                    "vLLM backend selected but VLLM_API_KEY is not set. Set it, or "
                    "select the local-first 'ollama' backend."
                )
        # ollama needs no key (utils.llm passes the literal "ollama" to the client).

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
        # reasoning_only / json_mode are advisory on the native path (no tool surface
        # is exposed here; the JSON contract is enforced in-prompt by callers).
        from utils.llm import chat_complete  # lazy: pulls openai/config

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        kwargs: dict = {"use_deep": use_deep}
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        return await chat_complete(messages, **kwargs)


class CortexBackend(ReasoningBackend):
    """Optional reasoning via the Cortex bridge (the ``cortex -z`` one-shot CLI).

    Adds no tools, memory or gating — IRA owns those in both modes (see
    docs/CORTEX_DEPENDENCY_FINDING.md). ``CortexBridge.ask`` is blocking, so it runs
    in a worker thread to keep the event loop free.
    """

    name = "cortex"

    def __init__(self) -> None:
        self._bridge = None

    def _bridge_instance(self):
        if self._bridge is None:
            from cortex_bridge import CortexBridge  # lazy

            self._bridge = CortexBridge()
        return self._bridge

    def validate(self) -> None:
        from cortex_bridge import CortexConfig  # lazy

        cfg = CortexConfig()
        # Resolve the configured binary the same way the bridge will at call time.
        if not shutil.which(cfg.cortex_bin):
            import os

            if not os.path.isfile(cfg.cortex_bin):
                raise ReasoningBackendError(
                    f"Cortex backend selected but the cortex executable was not found "
                    f"({cfg.cortex_bin!r}). Install Cortex and set IRA_CORTEX_BIN, or "
                    f"select the local-first 'ollama' backend."
                )

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
        bridge = self._bridge_instance()
        return await asyncio.to_thread(
            bridge.ask, prompt, system=system, reasoning_only=reasoning_only
        )


class MockBackend(ReasoningBackend):
    """Deterministic, dependency-free backend for tests and offline bring-up.

    Never touches the network and needs no secrets, so IRA can start fully on it.
    The reply echoes a stable, inspectable summary of the call.
    """

    name = "mock"

    def __init__(self, reply: Optional[str] = None) -> None:
        self._reply = reply

    def validate(self) -> None:
        return None  # no secrets, ever.

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
        if self._reply is not None:
            return self._reply
        tier = "deep" if use_deep else "fast"
        return f"[mock:{tier}] {prompt.strip()[:200]}"
