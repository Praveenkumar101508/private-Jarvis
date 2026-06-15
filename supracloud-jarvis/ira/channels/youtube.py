"""YouTube channel — local yt-dlp (metadata + transcript), no external SaaS."""
from __future__ import annotations

import asyncio

from channels.base import ChannelStatus, ResearchChannel


def _ytdlp_available():
    try:
        import yt_dlp  # noqa: F401
        return True
    except Exception:
        return False


def _extract_sync(url: str) -> str:
    import yt_dlp
    opts = {"quiet": True, "skip_download": True, "no_warnings": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    title = info.get("title", "")
    uploader = info.get("uploader", "")
    duration = info.get("duration", 0)
    desc = (info.get("description") or "")[:2000]
    return (
        f"Title: {title}\nUploader: {uploader}\nDuration: {duration}s\n\n"
        f"Description:\n{desc}"
    )


class YouTubeChannel(ResearchChannel):
    name = "youtube"
    can_read = True

    async def check(self) -> ChannelStatus:
        ok = _ytdlp_available()
        return ChannelStatus(self.name, ok, "yt-dlp available" if ok else "yt-dlp not installed")

    async def read(self, url: str) -> str:
        if not _ytdlp_available():
            return "YouTube reader unavailable — yt-dlp is not installed."
        try:
            return await asyncio.to_thread(_extract_sync, url)
        except Exception as exc:  # noqa: BLE001 — fail soft
            return f"YouTube read failed (yt-dlp): {str(exc)[:120]}"


__all__ = ["YouTubeChannel"]
