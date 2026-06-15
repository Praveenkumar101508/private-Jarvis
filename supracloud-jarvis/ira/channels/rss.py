"""RSS channel — local feedparser (feeds), no external SaaS."""
from __future__ import annotations

import asyncio

from channels.base import ChannelStatus, ResearchChannel


def _feedparser_available():
    try:
        import feedparser  # noqa: F401
        return True
    except Exception:
        return False


def _parse_sync(url: str) -> str:
    import feedparser
    feed = feedparser.parse(url)
    title = (feed.feed or {}).get("title", "") if hasattr(feed, "feed") else ""
    entries = (feed.entries or [])[:10]
    if not entries:
        return f"No entries in feed {url!r}."
    lines = [f"Feed: {title}".strip()] if title else []
    lines += [f"- {e.get('title', '').strip()}\n  {e.get('link', '')}" for e in entries]
    return "\n".join(lines)


class RSSChannel(ResearchChannel):
    name = "rss"
    can_read = True

    async def check(self) -> ChannelStatus:
        ok = _feedparser_available()
        return ChannelStatus(self.name, ok, "feedparser available" if ok else "feedparser not installed")

    async def read(self, url: str) -> str:
        if not _feedparser_available():
            return "RSS reader unavailable — feedparser is not installed."
        try:
            return await asyncio.to_thread(_parse_sync, url)
        except Exception as exc:  # noqa: BLE001 — fail soft
            return f"RSS read failed (feedparser): {str(exc)[:120]}"


__all__ = ["RSSChannel"]
