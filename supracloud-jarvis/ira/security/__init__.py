"""ira.security — security-spine helpers shared across paths.

Currently exposes the unified owner-gate (``owner_gate``), the single source of
truth for "is this query owner-only, and is this user allowed?" used by both the
router and the LangGraph biometric gate.
"""
