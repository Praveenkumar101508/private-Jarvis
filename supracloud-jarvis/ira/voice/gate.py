"""
ira/voice/gate.py — voice owner-gate decision (Prompt 4.4).

Wires the existing ECAPA biometric (voice/biometrics.is_owner_authenticated — DO NOT
rewrite it) into an access decision that the rest of the loop consumes:
  owner      -> full access (admin clearance; restricted domains allowed)
  non-owner  -> limited agent (public clearance; restricted domains blocked)

Fail-closed: any error, missing profile, low confidence, or too-short audio yields
NON-owner (verified in biometrics.py, and re-guarded here).
"""
from __future__ import annotations

import logging

logger = logging.getLogger("ira.voice.gate")


def decide_access(is_owner: bool) -> dict:
    """Pure mapping from a verified-owner flag to the access decision."""
    is_owner = bool(is_owner)
    return {
        "is_owner": is_owner,
        "clearance": "admin" if is_owner else "public",
        "restricted_allowed": is_owner,   # non-owner: restricted domains blocked
    }


async def gate_from_audio(audio_bytes: bytes, *, session_id: str = "unknown") -> dict:
    """Run the biometric on an utterance and return the access decision. Fail-closed."""
    is_owner = False
    try:
        from voice.biometrics import is_owner_authenticated
        is_owner = await is_owner_authenticated(audio_bytes, session_id=session_id)
    except Exception as exc:  # noqa: BLE001 — fail closed, never crash the turn
        logger.warning(f"Biometric gate failed closed: {exc}")
        is_owner = False
    return decide_access(is_owner)


__all__ = ["decide_access", "gate_from_audio"]
