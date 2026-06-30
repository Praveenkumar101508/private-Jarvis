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

from typing import Optional

# V1·Phase 3: the owner-gate logic now lives in ONE place. This module keeps its
# stable public API (restricted_domain / enforce_owner_gate / is_allowed) but
# delegates every decision to ira.security.owner_gate so the router and the
# LangGraph biometric gate can never drift apart again.
from security import owner_gate

#: regex-defined owner-only domains (re-exported for back-compat).
OWNER_ONLY_DOMAINS = owner_gate.OWNER_ONLY_DOMAINS

#: canonical non-owner refusal (re-exported for back-compat).
_REFUSAL = owner_gate.REFUSAL


def restricted_domain(query: str) -> Optional[str]:
    """Return the restricted domain a query targets, or None if it's a general query.

    The specific regex domain label (security / business / executor / system /
    architect_apply); see ``owner_gate.classify_domain``.
    """
    return owner_gate.classify_domain(query)


def enforce_owner_gate(query: str, is_owner: bool) -> Optional[str]:
    """Router-level gate. Returns a refusal string if a NON-owner targets an
    owner-only query (BLOCK); returns None when allowed.

    Fail-closed: the owner flag comes from the biometric gate, which returns False on any
    uncertainty/error; any owner-only signal (regex intent, restricted keyword, or owner
    name) by a non-owner is blocked here via the unified ``owner_gate``.
    """
    decision = owner_gate.evaluate(query, is_owner)
    return None if decision.allowed else decision.reason


def is_allowed(query: str, is_owner: bool) -> bool:
    """True if the (query, is_owner) pair is permitted past the router gate."""
    return owner_gate.evaluate(query, is_owner).allowed


__all__ = ["restricted_domain", "enforce_owner_gate", "is_allowed", "OWNER_ONLY_DOMAINS"]
