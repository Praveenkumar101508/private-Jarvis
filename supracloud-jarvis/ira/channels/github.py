"""GitHub channel — public repo read/search via the REST API (no SaaS reader)."""
from __future__ import annotations

import re

import httpx

from channels.base import ChannelStatus, ResearchChannel

_API = "https://api.github.com"
_REPO_RE = re.compile(r"github\.com/([^/\s]+)/([^/\s#?]+)")


class GitHubChannel(ResearchChannel):
    name = "github"
    can_read = True
    can_search = True

    async def check(self) -> ChannelStatus:
        try:
            async with httpx.AsyncClient(timeout=4) as c:
                r = await c.get(f"{_API}/rate_limit")
            return ChannelStatus(self.name, r.status_code == 200, f"GitHub API HTTP {r.status_code}")
        except Exception as exc:  # noqa: BLE001
            return ChannelStatus(self.name, False, f"GitHub API unreachable: {str(exc)[:80]}")

    async def read(self, url: str) -> str:
        m = _REPO_RE.search(url)
        if not m:
            return f"Not a recognizable public GitHub repo URL: {url!r}"
        owner, repo = m.group(1), m.group(2).removesuffix(".git")
        try:
            async with httpx.AsyncClient(timeout=8, headers={"Accept": "application/vnd.github+json"}) as c:
                meta = await c.get(f"{_API}/repos/{owner}/{repo}")
                meta.raise_for_status()
                d = meta.json()
                readme = await c.get(
                    f"{_API}/repos/{owner}/{repo}/readme",
                    headers={"Accept": "application/vnd.github.raw+json"},
                )
                readme_text = readme.text[:4000] if readme.status_code == 200 else "(no README)"
        except Exception as exc:  # noqa: BLE001 — fail soft
            return f"GitHub read failed: {str(exc)[:120]}"
        return (
            f"{d.get('full_name')} — ⭐{d.get('stargazers_count', 0)} — {d.get('language') or ''}\n"
            f"{d.get('description') or ''}\n\nREADME:\n{readme_text}"
        )

    async def search(self, query: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=8, headers={"Accept": "application/vnd.github+json"}) as c:
                r = await c.get(f"{_API}/search/repositories", params={"q": query, "per_page": 5})
                r.raise_for_status()
                items = (r.json() or {}).get("items", [])
        except Exception as exc:  # noqa: BLE001 — fail soft
            return f"GitHub search failed: {str(exc)[:120]}"
        if not items:
            return f"No public repositories found for {query!r}."
        return "\n\n".join(
            f"- {x.get('full_name')} (⭐{x.get('stargazers_count', 0)})\n  {x.get('html_url')}\n  {x.get('description') or ''}"
            for x in items
        )


__all__ = ["GitHubChannel"]
