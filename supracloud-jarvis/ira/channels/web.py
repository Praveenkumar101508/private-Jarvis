"""Web reader channel — self-hosted Crawl4AI (clean text from a URL, no SaaS)."""
from __future__ import annotations

import logging

import httpx

from channels.base import ChannelStatus, ResearchChannel
from config import get_settings
from utils.prompt_safety import check_adversarial_content, wrap_external_content

logger = logging.getLogger(__name__)


def _extract_text(data) -> str:
    """Pull clean text/markdown out of a Crawl4AI response (tolerant of shape)."""
    if isinstance(data, dict):
        # common shapes: {"results":[{"markdown":...}]} or {"markdown":...} / {"cleaned_html":...}
        if "results" in data and data["results"]:
            data = data["results"][0]
        for key in ("markdown", "cleaned_text", "text", "cleaned_html", "html"):
            val = data.get(key) if isinstance(data, dict) else None
            if val:
                return str(val).strip()
    return str(data)[:8000]


class WebChannel(ResearchChannel):
    name = "web"
    can_read = True

    def _url(self) -> str:
        return (getattr(get_settings(), "crawl4ai_url", "") or "").rstrip("/")

    async def check(self) -> ChannelStatus:
        base = self._url()
        if not base:
            return ChannelStatus(self.name, False, "CRAWL4AI_URL not set")
        try:
            async with httpx.AsyncClient(timeout=4) as c:
                r = await c.get(f"{base}/health")
            return ChannelStatus(self.name, r.status_code < 500, f"Crawl4AI HTTP {r.status_code}")
        except Exception as exc:  # noqa: BLE001
            return ChannelStatus(self.name, False, f"Crawl4AI unreachable: {str(exc)[:80]}")

    async def read(self, url: str) -> str:
        base = self._url()
        if not base:
            return "Web reader is unavailable — self-hosted Crawl4AI (CRAWL4AI_URL) is not configured."
        try:
            async with httpx.AsyncClient(timeout=25) as c:
                r = await c.post(f"{base}/crawl", json={"urls": [url]})
                r.raise_for_status()
                raw = _extract_text(r.json())
        except Exception as exc:  # noqa: BLE001 — fail soft
            return f"Web read failed (Crawl4AI): {str(exc)[:120]}"

        # P3.1: audit for injection attempts (log only — wrapping is the real guard)
        patterns = check_adversarial_content(raw)
        if patterns:
            logger.warning("Prompt-injection patterns detected in web content from %s: %s", url, patterns)

        # Wrap in untrusted-data delimiters so the model treats this as DATA
        return wrap_external_content(raw, source=url)


__all__ = ["WebChannel"]
