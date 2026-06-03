"""
ira/skills/security/ — Security Guardian, ported as a Hermes skill (Option A).

The reasoning/persona lives in SKILL.md. IRA keeps the security-critical pieces in
its OWN process (per MERGE_PLAN.md): the owner-gate, the active tools
(utils.security_tools: scan / lockdown / lift / dispatch) and the security_events DB
read. IRA gathers events + runs the requested tool, then calls analyze_security(),
which sends the persona + that context through the Hermes bridge for analysis —
replacing the old direct chat_complete() call in agents/security.py.

This module imports ONLY the bridge (no DB/tool imports), so the reasoning is unit-
testable without IRA's runtime; the owner-gate / tools / DB stay in agents/security.py
and never leave IRA.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Sequence

from hermes_bridge import HermesBridge

_SKILL_MD = Path(__file__).with_name("SKILL.md")


def load_persona(owner_name: str = "the owner") -> str:
    """Return the security persona from SKILL.md (body after the YAML frontmatter)."""
    text = _SKILL_MD.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)  # frontmatter is delimited by --- ... ---
        text = parts[2] if len(parts) == 3 else text
    return text.strip().replace("{owner_name}", owner_name)


def analyze_security(
    query: str,
    *,
    events: Optional[Sequence[dict]] = None,
    tool_output: Optional[str] = None,
    memory_context: Optional[str] = None,
    owner_name: str = "the owner",
    bridge: Optional[HermesBridge] = None,
) -> str:
    """Security reasoning step (Option A): persona + IRA-gathered context -> bridge.

    `events`, `tool_output`, `memory_context` are produced by IRA's existing code
    (security_tools + the security_events DB read) and passed in. This mirrors the
    message assembly of agents/security.py::security_guardian, but routes the
    reasoning through the out-of-process Hermes engine instead of chat_complete().
    """
    bridge = bridge or HermesBridge()
    system = load_persona(owner_name)
    if events:
        system += (
            f"\n\nCurrent unresolved security events ({len(events)} total):\n"
            + json.dumps(list(events), indent=2)
        )
    else:
        system += "\n\nNo unresolved security events in the database at this time."
    if tool_output:
        system += f"\n\nActive tool execution result (IRA just ran):\n{tool_output}"
    if memory_context:
        system += f"\n\nRelated past security context:\n{memory_context}"
    return bridge.ask(query, system=system)


__all__ = ["analyze_security", "load_persona"]
