"""
ira/utils/approval.py — reusable approval guardrail for side-effecting actions.

Every real-world side effect (sending email, calendar writes, file writes/deletes,
executor commands) goes through a two-step flow:

  1. draft()   -> produce a human-readable PREVIEW and a one-time pending token,
                  returned to the user. NOTHING is executed yet.
  2. confirm() -> only when an explicit confirmation referencing that token arrives
                  is the action executed.

Pending actions are stored keyed by (owner, token) with a short TTL, so an
unconfirmed or stale draft simply expires and never runs. Tokens are one-shot and
scoped to the owner that created them (another user cannot confirm them).

The store is in-process, which matches the single-process native deployment; swap
the dict for a Redis-backed store if the API is ever scaled to multiple workers.
"""
from __future__ import annotations

import inspect
import secrets
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, Union

# A zero-arg callable performing the side effect; may be sync or async.
ExecuteFn = Callable[[], Union[Any, Awaitable[Any]]]


@dataclass
class Draft:
    token: str
    action: str
    preview: str
    expires_in: float


@dataclass
class ConfirmResult:
    status: str                      # "executed" | "expired" | "not_found"
    action: Optional[str] = None
    result: Any = None

    @property
    def executed(self) -> bool:
        return self.status == "executed"


@dataclass
class _Pending:
    owner: str
    action: str
    preview: str
    execute: ExecuteFn
    expires_at: float


class ApprovalGuardrail:
    """Two-step draft -> confirm gate for side-effecting actions."""

    def __init__(
        self,
        *,
        ttl_seconds: float = 300.0,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self._now = now
        self._pending: dict[tuple[str, str], _Pending] = {}

    def _purge_expired(self) -> None:
        t = self._now()
        for key in [k for k, p in self._pending.items() if t >= p.expires_at]:
            del self._pending[key]

    def draft(self, *, owner: str, action: str, preview: str, execute: ExecuteFn) -> Draft:
        """Stage a side effect: store it under a fresh token and return its preview.

        The action is NOT executed here — only when confirm() is called with the
        returned token by the same owner.
        """
        self._purge_expired()
        token = secrets.token_urlsafe(8)
        self._pending[(owner, token)] = _Pending(
            owner=owner, action=action, preview=preview, execute=execute,
            expires_at=self._now() + self.ttl_seconds,
        )
        return Draft(token=token, action=action, preview=preview, expires_in=self.ttl_seconds)

    async def confirm(self, *, owner: str, token: str) -> ConfirmResult:
        """Execute the staged action for (owner, token), once.

        Returns status "not_found" (unknown token / wrong owner / already used),
        "expired" (TTL elapsed), or "executed" (with the action's result).
        """
        key = (owner, token)
        pending = self._pending.get(key)
        if pending is None:
            return ConfirmResult(status="not_found")
        if self._now() >= pending.expires_at:
            del self._pending[key]
            return ConfirmResult(status="expired", action=pending.action)

        del self._pending[key]  # one-shot: consume before executing
        result = pending.execute()
        if inspect.isawaitable(result):
            result = await result
        return ConfirmResult(status="executed", action=pending.action, result=result)

    def pending_count(self, owner: Optional[str] = None) -> int:
        """Number of live (unexpired) pending actions, optionally for one owner."""
        self._purge_expired()
        if owner is None:
            return len(self._pending)
        return sum(1 for (o, _tok) in self._pending if o == owner)


# App-wide singleton for the single-process native deployment.
guardrail = ApprovalGuardrail()

__all__ = ["ApprovalGuardrail", "Draft", "ConfirmResult", "guardrail"]
