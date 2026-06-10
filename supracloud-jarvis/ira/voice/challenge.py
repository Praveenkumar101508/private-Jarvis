"""
ira/voice/challenge.py — spoken challenge-response for high-stakes voice actions (4.5).

Before executing a high-stakes owner action by voice (self-modification, security,
sending comms), the system issues a random phrase the user must SPEAK BACK. The
spoken-back utterance must (a) transcribe to the issued phrase and (b) pass the
biometric — defeating replay of a single captured "yes". Mirrors the existing
/voice/challenge scaffolding's phrase pool; the store here is in-process with a
short TTL and is one-shot.
"""
from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass
from typing import Callable, Optional

# Short, unambiguous phrases (mirrors api/routes/voice.py's _CHALLENGE_PHRASES).
_CHALLENGE_PHRASES = [
    "IRA authenticate now",
    "voice lock open",
    "secure access granted",
    "identity confirm",
    "biometric verify",
    "owner access code",
    "unlock voice gate",
    "speak to proceed",
]

_NORM_RE = re.compile(r"[^a-z0-9 ]+")


def _normalize(text: str) -> str:
    return _NORM_RE.sub("", (text or "").lower()).strip()


@dataclass
class _Pending:
    owner: str
    phrase: str
    expires_at: float


@dataclass
class VerifyResult:
    ok: bool
    reason: str = ""


class ChallengeManager:
    """Issue and one-shot verify spoken challenge phrases (in-process, TTL'd)."""

    def __init__(self, *, ttl_seconds: float = 60.0, now: Callable[[], float] = time.monotonic):
        self.ttl_seconds = ttl_seconds
        self._now = now
        self._pending: dict[str, _Pending] = {}

    def _purge(self) -> None:
        t = self._now()
        for cid in [c for c, p in self._pending.items() if t >= p.expires_at]:
            del self._pending[cid]

    def issue(self, owner: str) -> dict:
        """Issue a fresh challenge for an owner action; returns id + phrase + ttl."""
        self._purge()
        challenge_id = secrets.token_urlsafe(8)
        phrase = secrets.choice(_CHALLENGE_PHRASES)
        self._pending[challenge_id] = _Pending(owner, phrase, self._now() + self.ttl_seconds)
        return {"challenge_id": challenge_id, "phrase": phrase, "expires_in": self.ttl_seconds}

    def verify(self, *, owner: str, challenge_id: str, spoken_text: str, biometric_ok: bool) -> VerifyResult:
        """One-shot verify: the spoken phrase must match AND the biometric must pass."""
        pending = self._pending.pop(challenge_id, None)   # consume regardless of outcome
        if pending is None:
            return VerifyResult(False, "challenge not found or already used")
        if self._now() >= pending.expires_at:
            return VerifyResult(False, "challenge expired")
        if pending.owner != owner:
            return VerifyResult(False, "challenge belongs to a different owner")
        if not biometric_ok:
            return VerifyResult(False, "biometric verification failed")
        if _normalize(spoken_text) != _normalize(pending.phrase):
            return VerifyResult(False, "spoken phrase did not match")
        return VerifyResult(True, "verified")


# App-wide singleton for the voice service.
challenges = ChallengeManager()

__all__ = ["ChallengeManager", "VerifyResult", "challenges"]
