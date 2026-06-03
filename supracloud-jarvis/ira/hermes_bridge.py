"""
ira/hermes_bridge.py — the ONLY file in IRA that talks to Hermes.

Hermes runs OUT-OF-PROCESS as an OpenAI-compatible gateway (default 127.0.0.1:8642).
This module is a thin HTTP client to that gateway, using IRA's existing `openai`
client — nothing in IRA imports Hermes. Swapping engines = rewriting only this file
(the anti-corruption layer / exit hatch described in MERGE_PLAN.md).

Config via env (see ira/config/hermes.env.example):
  IRA_HERMES_URL    default http://127.0.0.1:8642/v1
  IRA_HERMES_KEY    == Hermes API_SERVER_KEY (required by the gateway)
  IRA_HERMES_MODEL  default "hermes-agent" (the id the gateway exposes at /v1/models)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from openai import OpenAI  # IRA already depends on openai — NOT hermes-agent


@dataclass(frozen=True)
class HermesConfig:
    base_url: str = os.getenv("IRA_HERMES_URL", "http://127.0.0.1:8642/v1")
    api_key: str = os.getenv("IRA_HERMES_KEY", "")
    model: str = os.getenv("IRA_HERMES_MODEL", "hermes-agent")
    timeout: float = float(os.getenv("IRA_HERMES_TIMEOUT", "300"))


class HermesBridge:
    """Thin, swappable HTTP wrapper around the Hermes gateway.

    Keep this minimal — wrap only what IRA actually uses. Everything IRA needs
    from Hermes passes through methods on this class.
    """

    def __init__(self, cfg: Optional[HermesConfig] = None) -> None:
        self.cfg = cfg or HermesConfig()
        self._client = OpenAI(
            base_url=self.cfg.base_url,
            api_key=self.cfg.api_key or "not-needed",  # gateway is key-gated
            timeout=self.cfg.timeout,
        )

    def ask(self, prompt: str, *, system: Optional[str] = None, session_key: Optional[str] = None) -> str:
        """Send a message to the Hermes gateway; return the final text reply.

        NOTE (verified Phase 2): the gateway is an AGENT endpoint with its own system
        prompt — a client `system` role is NOT reliably honored. So when `system`
        context (e.g. a skill persona + data) is provided we fold it into the user
        message, which the agent does read.

        session_key -> X-Hermes-Session-Key header (per-tenant memory isolation, Phase 5).
        """
        content = f"{system}\n\n---\n\n{prompt}" if system else prompt
        kwargs = {}
        if session_key:
            kwargs["extra_headers"] = {"X-Hermes-Session-Key": session_key}
        resp = self._client.chat.completions.create(
            model=self.cfg.model,
            messages=[{"role": "user", "content": content}],
            **kwargs,
        )
        return (resp.choices[0].message.content or "").strip()

    def deliberate(self, question: str, *, owner_name: str = "the owner",
                   memory_context: Optional[str] = None) -> str:
        """5-agent 'Grok-style' deliberation (Expert Mode) — 4 specialists + supervisor.

        Orchestration lives in ira/subagents/ (lazy import avoids a circular dependency);
        each role reasons through this same bridge.
        """
        from subagents import deliberate as _deliberate
        return _deliberate(question, bridge=self, owner_name=owner_name, memory_context=memory_context)


__all__ = ["HermesBridge", "HermesConfig"]
