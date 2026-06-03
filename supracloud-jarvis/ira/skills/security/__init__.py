"""
ira/skills/security/ — Security Guardian, ported as a Hermes skill (Option A).

The reasoning/persona lives in SKILL.md. IRA keeps the security-critical pieces in
its OWN process (per MERGE_PLAN.md): the owner-gate, the active tools
(utils.security_tools: scan / lockdown / lift / dispatch) and the security_events DB
read. IRA gathers events + runs the requested tool, then calls analyze_security(),
which sends the persona + that context through the Hermes bridge — replacing the old
direct chat_complete() call in agents/security.py. Security-critical ops never leave IRA.
"""
from __future__ import annotations

import json
from typing import Optional, Sequence

from hermes_bridge import HermesBridge
from skills._common import load_persona as _load_persona, run_skill


def load_persona(owner_name: str = "the owner") -> str:
    """The security persona from SKILL.md (kept for back-compat / tests)."""
    return _load_persona("security", owner_name=owner_name)


def analyze_security(
    query: str,
    *,
    events: Optional[Sequence[dict]] = None,
    tool_output: Optional[str] = None,
    memory_context: Optional[str] = None,
    owner_name: str = "the owner",
    bridge: Optional[HermesBridge] = None,
    session_key: Optional[str] = None,
) -> str:
    """Security reasoning step (Option A): persona + IRA-gathered context -> bridge.

    `events`, `tool_output`, `memory_context` are produced by IRA's existing code
    (security_tools + the security_events DB read) and passed in. Mirrors the message
    assembly of agents/security.py::security_guardian, routing the reasoning through
    the out-of-process Hermes engine.
    """
    blocks = []
    if events:
        blocks.append(
            "You have NO access to any system, files, logs, or shell. The following is the "
            f"COMPLETE, already-collected set of {len(events)} unresolved security event(s) — "
            "analyze exactly these and produce your report; do not try to gather more data:\n"
            + json.dumps(list(events), indent=2)
        )
    else:
        blocks.append(
            "You have NO access to any system, files, or logs. There are currently no "
            "unresolved security events to analyze."
        )
    if tool_output:
        blocks.append(f"Result of an action IRA already executed:\n{tool_output}")
    if memory_context:
        blocks.append(f"Related past security context:\n{memory_context}")
    return run_skill(
        "security", query, context_blocks=blocks, owner_name=owner_name,
        bridge=bridge, session_key=session_key,
    )


__all__ = ["analyze_security", "load_persona"]
