"""ira/router.py — router-level owner-gate enforcement (Phase 4, part 3).

The ECAPA biometric gate (voice/biometrics.py) is verified **fail-closed** and already
runs in the voice pipeline (voice/agent.py), which passes `is_owner` to the API. This
module is the second half the gate's own docstring calls out: it BLOCKS non-owners from
**restricted (owner-only) domains** at the router, fail-closed. We classify restricted
intent deterministically in IRA (regex) — we do NOT delegate the security decision to
the engine.

Restricted (owner-only): security ops, business/lead data, command execution,
OS/desktop control, and architect apply/self-modification. General domains (chat,
tutoring, research, creative work) stay open to non-owners.

Enforcement is independent of WHICH engine answers — it runs before any skill/bridge
dispatch. The full query→skill dispatch is wired at the LangGraph-router cutover.
"""
from __future__ import annotations

import re
from typing import Optional

# domain -> intent pattern. Mirrors the owner-sensitive triggers in the agents:
# security_tools (lockdown/scan/dispatch), website (business data), executor (commands),
# digital (OS control), architect (apply/implement self-modification).
_RESTRICTED: dict[str, re.Pattern] = {
    "security": re.compile(
        r"(lock\s*down|lockdown|panic|emergency\s+lock|scan.{0,15}(threat|network|intrus)|"
        r"security\s+event|firewall|intrusion|"
        r"(text|message|send|notify|alert).{0,20}(my\s+phone|telegram|pocket|secure))", re.I),
    "business": re.compile(
        r"\b(lead|leads|booking|bookings|revenue|conversion\s+rate|business\s+metric|"
        r"investor|client\s*[-→]?\s*agent)\b", re.I),
    "executor": re.compile(
        r"\b(run|execute)\b.{0,20}\b(command|shell|terminal|pytest|docker|git)\b", re.I),
    "system": re.compile(
        r"\b(open|launch|start)\b.{0,20}\b(app|application|vs\s*code|vscode|terminal|"
        r"browser|chrome|firefox|powershell|notepad|explorer)\b", re.I),
    "architect_apply": re.compile(r"\barchitect\s+(apply|implement|dry\s*run)\b", re.I),
}

OWNER_ONLY_DOMAINS = frozenset(_RESTRICTED)

_REFUSAL = (
    "That action is restricted to the verified owner. Please authenticate with your "
    "voice biometric to proceed."
)


def restricted_domain(query: str) -> Optional[str]:
    """Return the restricted domain a query targets, or None if it's a general query."""
    q = query or ""
    for domain, pattern in _RESTRICTED.items():
        if pattern.search(q):
            return domain
    return None


def enforce_owner_gate(query: str, is_owner: bool) -> Optional[str]:
    """Router-level gate. Returns a refusal string if a NON-owner targets a restricted
    domain (BLOCK); returns None when allowed.

    Fail-closed: the owner flag comes from the biometric gate, which returns False on any
    uncertainty/error; any restricted-intent match by a non-owner is blocked here.
    """
    if is_owner:
        return None
    if restricted_domain(query) is not None:
        return _REFUSAL
    return None


def is_allowed(query: str, is_owner: bool) -> bool:
    """True if the (query, is_owner) pair is permitted past the router gate."""
    return enforce_owner_gate(query, is_owner) is None


__all__ = ["restricted_domain", "enforce_owner_gate", "is_allowed", "OWNER_ONLY_DOMAINS"]
