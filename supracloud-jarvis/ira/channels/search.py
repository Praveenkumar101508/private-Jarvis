"""SearXNG search channel — self-hosted metasearch (no external SaaS)."""
from __future__ import annotations

import httpx

from channels.base import ChannelStatus, ResearchChannel
from config import get_settings


class SearchChannel(ResearchChannel):
    name = "search"
    can_search = True

    def _url(self) -> str:
        return (get_settings().searxng_url or "").rstrip("/")

    async def check(self) -> ChannelStatus:
        base = self._url()
        if not base:
            return ChannelStatus(self.name, False, "SEARXNG_URL not set")
        try:
            async with httpx.AsyncClient(timeout=4) as c:
                r = await c.get(f"{base}/search", params={"q": "ping", "format": "json"})
            return ChannelStatus(self.name, r.status_code == 200, f"SearXNG HTTP {r.status_code}")
        except Exception as exc:  # noqa: BLE001
            return ChannelStatus(self.name, False, f"SearXNG unreachable: {str(exc)[:80]}")

    async def search(self, query: str) -> str:
        base = self._url()
        if not base:
            return "Web search is unavailable — self-hosted SearXNG (SEARXNG_URL) is not configured."
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.get(f"{base}/search", params={"q": query, "format": "json"})
                r.raise_for_status()
                results = (r.json() or {}).get("results", [])[:5]
        except Exception as exc:  # noqa: BLE001 — fail soft
            return f"Web search failed (SearXNG): {str(exc)[:120]}"
        if not results:
            return f"No web results found for {query!r}."
        return "\n\n".join(
            f"- {x.get('title', '').strip()}\n  {x.get('url', '')}\n  {x.get('content', '').strip()}"
            for x in results
        )


__all__ = ["SearchChannel"]
