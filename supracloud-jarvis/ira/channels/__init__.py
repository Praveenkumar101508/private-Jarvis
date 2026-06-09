"""
ira/channels/ — the pluggable, sovereign web-research layer.

Agent-Reach's swappable-channel pattern rebuilt on LOCAL / self-hosted backends only
(SearXNG, Crawl4AI, yt-dlp, GitHub public REST, feedparser). Nothing routes through a
cloud reader/search SaaS (no Jina, no Exa). Every channel fails soft.

  search(query)  -> SearXNG (or the github channel for repo search)
  read(url)      -> auto-routed by host: youtube -> yt-dlp, github.com -> REST,
                    otherwise the Crawl4AI web reader
  doctor()       -> per-channel health (like `agent-reach doctor`)
"""
from __future__ import annotations

import asyncio
from typing import Optional
from urllib.parse import urlparse

from channels.base import ChannelStatus, ResearchChannel
from channels.github import GitHubChannel
from channels.rss import RSSChannel
from channels.search import SearchChannel
from channels.web import WebChannel
from channels.youtube import YouTubeChannel

_CHANNELS: dict[str, ResearchChannel] = {
    c.name: c for c in (SearchChannel(), WebChannel(), YouTubeChannel(), GitHubChannel(), RSSChannel())
}


def get_channel(name: str) -> Optional[ResearchChannel]:
    return _CHANNELS.get(name)


def all_channels() -> list[ResearchChannel]:
    return list(_CHANNELS.values())


def channel_for_url(url: str) -> ResearchChannel:
    """Pick the read channel for a URL by host (youtube/github -> their channel, else web)."""
    host = (urlparse(url).hostname or "").lower()
    if "youtube.com" in host or host.endswith("youtu.be"):
        return _CHANNELS["youtube"]
    if host.endswith("github.com"):
        return _CHANNELS["github"]
    return _CHANNELS["web"]


async def doctor() -> dict[str, dict]:
    """Report each channel's status (the `research doctor`). Never raises."""
    names = list(_CHANNELS)
    results = await asyncio.gather(
        *[_CHANNELS[n].check() for n in names], return_exceptions=True
    )
    out: dict[str, dict] = {}
    for name, res in zip(names, results):
        ch = _CHANNELS[name]
        if isinstance(res, Exception):
            out[name] = {"ok": False, "detail": f"check error: {str(res)[:80]}",
                         "search": ch.can_search, "read": ch.can_read}
        else:
            out[name] = {"ok": res.ok, "detail": res.detail,
                         "search": ch.can_search, "read": ch.can_read}
    return out


async def search(query: str, *, channel: str = "search") -> str:
    """Search via the named channel (default SearXNG). Fail soft."""
    ch = _CHANNELS.get(channel)
    if ch is None or not ch.can_search:
        return f"No search channel named {channel!r}."
    return await ch.search(query)


async def read(url: str, *, channel: Optional[str] = None) -> str:
    """Read a URL via the matching (or named) channel. Fail soft."""
    ch = _CHANNELS.get(channel) if channel else channel_for_url(url)
    if ch is None or not ch.can_read:
        return f"No read channel available for {url!r}."
    return await ch.read(url)


__all__ = [
    "ChannelStatus", "ResearchChannel", "get_channel", "all_channels",
    "channel_for_url", "doctor", "search", "read",
]
