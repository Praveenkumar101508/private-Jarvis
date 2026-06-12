"""
ira/hermes_bridge.py — the ONLY file in IRA that talks to Hermes.

Hermes 0.15.2 runs OUT-OF-PROCESS as a native CLI. IRA reaches the FULL Hermes
agent by invoking ``hermes -z "<prompt>"`` (one-shot mode: runs the agent against
the LOCAL Ollama model configured in Hermes' own config.yaml, and prints ONLY the
final response text to stdout). Nothing in IRA imports hermes-agent — its hard
pins conflict with IRA's (CLAUDE.md rule 3) — so this module shells out instead.
Swapping engines = rewriting only this file (the anti-corruption layer / exit
hatch in MERGE_PLAN.md).

WHY SUBPROCESS, NOT HTTP (verified against the installed 0.15.2 on 2026-06-11):
Hermes 0.15.2 ships no local, key-gated, OpenAI-compatible ``/v1`` server.
``hermes gateway`` is the *messaging* gateway (Telegram/Discord/...); ``hermes
proxy`` only forwards to *cloud* OAuth providers (nous/xai) and accepts any
bearer token. Neither gives a sovereign, Ollama-backed, key-gated endpoint, and
``API_SERVER_KEY`` / port ``8642`` / a ``/v1/models`` route exist nowhere in the
package. The one-shot CLI is the sovereign seam.

SOVEREIGNTY: the model / provider / base_url live in Hermes' own config.yaml
(provider: custom, base_url: http://localhost:11434/v1, default: qwen3:14b,
context_length: 65536, ollama_num_ctx: 65536) — nothing leaves the box. We do
NOT pass ``--ignore-user-config`` (that falls back to Hermes' built-in OpenRouter
*cloud* default).

Config via env (see ira/config/hermes.env.example):
  IRA_USE_HERMES     "true" routes IRA through Hermes (read by callers, not here).
  IRA_HERMES_BIN     path to the hermes executable. Default: resolve ``hermes`` on
                     PATH, else %LOCALAPPDATA%\\hermes\\hermes-agent\\venv\\Scripts\\hermes.exe.
  IRA_HERMES_TIMEOUT per-call timeout in seconds (default 300).
  IRA_HERMES_CWD     working dir for the agent subprocess (default: this file's dir).
  IRA_HERMES_MODEL   advisory only here — the model is governed by Hermes
                     config.yaml. Kept for interface back-compat.
  IRA_HERMES_URL /   retained for back-compat with the prior HTTP-gateway design;
  IRA_HERMES_KEY     UNUSED on the subprocess path (no gateway, no key gate).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


def _default_hermes_bin() -> str:
    """Resolve the hermes executable: env override -> PATH -> known native install."""
    env_bin = os.getenv("IRA_HERMES_BIN")
    if env_bin:
        return env_bin
    found = shutil.which("hermes")
    if found:
        return found
    local = os.getenv("LOCALAPPDATA", "")
    if local:
        cand = Path(local) / "hermes" / "hermes-agent" / "venv" / "Scripts" / "hermes.exe"
        if cand.exists():
            return str(cand)
    return "hermes"  # last resort; surfaces a clear FileNotFoundError if truly absent


@dataclass(frozen=True)
class HermesConfig:
    # Retained for back-compat with the prior HTTP bridge (UNUSED on this path) ---
    base_url: str = os.getenv("IRA_HERMES_URL", "http://127.0.0.1:8642/v1")
    api_key: str = os.getenv("IRA_HERMES_KEY", "")
    # Advisory: the live model/provider live in Hermes config.yaml, not here -------
    model: str = os.getenv("IRA_HERMES_MODEL", "hermes-agent")
    # Live on the subprocess path -------------------------------------------------
    timeout: float = float(os.getenv("IRA_HERMES_TIMEOUT", "300"))
    hermes_bin: str = field(default_factory=_default_hermes_bin)
    cwd: str = os.getenv("IRA_HERMES_CWD", str(Path(__file__).resolve().parent))


class HermesBridge:
    """Thin, swappable subprocess wrapper around the local Hermes agent CLI.

    Keep this minimal — wrap only what IRA actually uses. Everything IRA needs
    from Hermes passes through methods on this class.
    """

    def __init__(self, cfg: Optional[HermesConfig] = None) -> None:
        self.cfg = cfg or HermesConfig()

    def ask(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        session_id: Optional[str] = None,
        user_key: Optional[str] = None,
        session_key: Optional[str] = None,
    ) -> str:
        """Run the Hermes agent on ``prompt`` (one-shot) and return the final text.

        ``system`` (e.g. a skill persona + gathered data) is prepended to the prompt,
        since ``hermes -z`` has no separate system channel. ``session_id``, ``user_key``
        and ``session_key`` are accepted for call-site compatibility but intentionally
        NOT used here: ``hermes -z`` one-shots can't resume a per-conversation session
        (verified — ``--continue <name> -z`` neither stores nor recalls across calls),
        so thread continuity is IRA-owned: the caller (api/routes/chat._hermes_route)
        loads the recent turns from Postgres and passes them in as context. Per-tenant
        long-term memory isolation remains a later-phase task (CLAUDE.md). ``session_key``
        is the deprecated alias for ``user_key``.
        """
        _ = (session_id, user_key, session_key)  # accepted for call-site compat; see note

        full_prompt = f"{system.strip()}\n\n{prompt}" if system else prompt

        # Stateless one-shot — each call is isolated. We do NOT pass --continue (it
        # doesn't persist/resume across one-shots and bleeds the most-recent session).
        cmd: List[str] = [self.cfg.hermes_bin, "--accept-hooks", "-z", full_prompt]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.cfg.timeout,
                cwd=self.cfg.cwd or None,
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"Hermes agent timed out after {self.cfg.timeout:.0f}s") from e
        except FileNotFoundError as e:
            raise RuntimeError(
                f"Hermes executable not found: {self.cfg.hermes_bin!r}. "
                "Set IRA_HERMES_BIN or ensure `hermes` is on PATH."
            ) from e

        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(f"Hermes agent exited {proc.returncode}: {err[:2000]}")
        return (proc.stdout or "").strip()

    def deliberate(self, question: str, *, owner_name: str = "the owner",
                   memory_context: Optional[str] = None) -> str:
        """5-agent 'Grok-style' deliberation (Expert Mode) — 4 specialists + supervisor.

        Orchestration lives in ira/subagents/ (lazy import avoids a circular dependency);
        each role reasons through this same bridge.
        """
        from subagents import deliberate as _deliberate
        return _deliberate(question, bridge=self, owner_name=owner_name, memory_context=memory_context)


__all__ = ["HermesBridge", "HermesConfig"]
