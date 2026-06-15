"""
ira/channels/base.py — the uniform research-channel interface.

Inspired by Agent-Reach's pluggable-channel pattern, but every channel runs on a
LOCAL / self-hosted backend so nothing leaves the box. Each channel exposes a
uniform surface: an async check() health probe and, depending on capability,
search(query) and/or read(url). All methods FAIL SOFT — they return a clear
message instead of raising, so a missing/unreachable backend never breaks a turn.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ChannelStatus:
    name: str
    ok: bool
    detail: str


class ResearchChannel:
    """Base class for a research channel. Override check() and the capabilities used."""

    name: str = "channel"
    can_search: bool = False
    can_read: bool = False

    async def check(self) -> ChannelStatus:  # pragma: no cover - overridden
        raise NotImplementedError

    async def search(self, query: str) -> str:
        return f"The '{self.name}' channel does not support search."

    async def read(self, url: str) -> str:
        return f"The '{self.name}' channel does not support read."


__all__ = ["ChannelStatus", "ResearchChannel"]
