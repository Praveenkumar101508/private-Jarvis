"""
ira/security/owner_gate.py — the SINGLE source of truth for the owner-gate.

Before V1·Phase 3 the same security question ("is this query owner-only, and is
this user allowed?") was answered by two independent classifiers with different
vocabularies:

  * router.py        — a regex intent map (security ops, business data, command
                       execution, OS control, architect self-modification).
  * agents/supervisor.is_restricted_domain — a keyword list (config/routing.yaml
                       ``restricted_keywords``) plus the owner's first name.

So the same input could be blocked on one path and waved through on the other
(proven by tests/security/test_gate_consistency.py). This module unifies them:
one ``evaluate()`` returns a typed :class:`GateDecision`, and both paths call it.

OWNER-ONLY = regex-intent match  OR  restricted-keyword match  OR  owner-name
match. The union is deliberately **fail-closed**: any owner-only signal on any
path blocks a non-owner on every path. The regex domain label is preserved for
callers that need it (``classify_domain``).

GRACEFUL DEGRADATION: the regex check is pure and always available, so this module
imports cleanly with no config. The keyword list and owner name are loaded
best-effort (they need routing.yaml / Settings); if those are unavailable the gate
falls back to the always-present regex signal rather than raising — this keeps
``router`` importable and usable without a full Settings, exactly as before.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
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

#: the set of regex-defined owner-only domain names.
OWNER_ONLY_DOMAINS = frozenset(_RESTRICTED)

#: canonical refusal surfaced to a non-owner at the router boundary.
REFUSAL = (
    "That action is restricted to the verified owner. Please authenticate with your "
    "voice biometric to proceed."
)


@dataclass(frozen=True)
class GateDecision:
    """The typed outcome of an owner-gate evaluation — identical regardless of path."""

    allowed: bool
    reason: str                 # refusal text when blocked, else ""
    risk_level: str             # "restricted" | "public"
    required_role: str          # "owner" | "any"
    audit_event_type: str       # "owner_gate.block" | "owner_gate.allow_owner" | "owner_gate.allow"
    domain: Optional[str] = None  # regex domain label when matched (richer audit)


# ── signal sources ──────────────────────────────────────────────────────────

def classify_domain(query: str) -> Optional[str]:
    """Return the regex-defined owner-only domain a query targets, or None.

    Pure and config-free; preserved for callers that need the specific label
    (e.g. router.restricted_domain).
    """
    q = query or ""
    for domain, pattern in _RESTRICTED.items():
        if pattern.search(q):
            return domain
    return None


def _restricted_keywords() -> frozenset:
    """Owner-only keyword phrases from config/routing.yaml (best-effort)."""
    try:
        from utils.yaml_config import get_restricted_keywords

        return get_restricted_keywords()
    except Exception:  # noqa: BLE001 - missing/!loadable yaml → keyword signal absent
        return frozenset()


def _owner_first_name() -> str:
    """The owner's first name, lowercased, from Settings (best-effort).

    Returns "" when Settings is unavailable or still the placeholder default, so a
    stray token can never match an unconfigured deployment.
    """
    try:
        from config import get_settings

        name = (get_settings().owner_name or "").strip()
    except Exception:  # noqa: BLE001 - no Settings (e.g. bare router import) → no name signal
        return ""
    first = name.split()[0].lower() if name.split() else ""
    if not first or first.startswith("change_me"):
        return ""
    return first


def is_owner_only(query: str) -> bool:
    """True if the query is owner-only by ANY signal (regex ∪ keyword ∪ owner name).

    Fail-closed union: this is the consistent answer both paths must use.
    """
    q = (query or "").lower()
    if classify_domain(query) is not None:
        return True
    if any(kw in q for kw in _restricted_keywords()):
        return True
    owner_first = _owner_first_name()
    return bool(owner_first and owner_first in q)


# ── the single decision point ────────────────────────────────────────────────

def evaluate(query: str, is_owner: bool) -> GateDecision:
    """The owner-gate's single source of truth.

    Same (query, is_owner) → same GateDecision on every path. Owner-only is the
    fail-closed union of all signals; a verified owner is always allowed.
    """
    domain = classify_domain(query)
    restricted = is_owner_only(query)

    if not restricted:
        return GateDecision(
            allowed=True, reason="", risk_level="public",
            required_role="any", audit_event_type="owner_gate.allow", domain=None,
        )
    if is_owner:
        return GateDecision(
            allowed=True, reason="", risk_level="restricted",
            required_role="owner", audit_event_type="owner_gate.allow_owner", domain=domain,
        )
    return GateDecision(
        allowed=False, reason=REFUSAL, risk_level="restricted",
        required_role="owner", audit_event_type="owner_gate.block", domain=domain,
    )


__all__ = [
    "GateDecision", "evaluate", "is_owner_only", "classify_domain",
    "OWNER_ONLY_DOMAINS", "REFUSAL",
]
