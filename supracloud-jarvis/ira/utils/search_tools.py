"""
IRA Real-Time Search Tools — Web Search + X (Twitter) Search.

Web search uses DuckDuckGo (no API key required, async wrapper).
X/Twitter search uses Twitter API v2 if TWITTER_BEARER_TOKEN is set,
otherwise falls back to DuckDuckGo site:twitter.com search.

Designed to run before LLM inference so results are injected as live context.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re

logger = logging.getLogger("ira.search")

_TWITTER_BEARER = os.getenv("TWITTER_BEARER_TOKEN", "")

# Detect queries that need current information
_SEARCH_RE = re.compile(
    r"\b(today|yesterday|this week|this month|current|latest|recent|breaking|"
    r"news|now|2024|2025|2026|price of|stock price|weather|who is|what is happening|"
    r"just announced|just released|search for|look up|find|trending|viral|"
    r"x\.com|twitter|tweet)\b",
    re.I,
)

# Detect queries specifically about X/Twitter content
_X_RE = re.compile(
    r"\b(twitter|x\.com|tweet|trending on x|what.*x|"
    r"people saying|everyone.*saying|social.*opinion|viral)\b",
    re.I,
)

# Detect image generation requests
_IMAGE_GEN_RE = re.compile(
    r"\b(generate\s+(an?\s+)?image|create\s+(an?\s+)?(image|picture|photo|art|drawing)|"
    r"draw\s+(me\s+)?|make\s+(an?\s+)?(image|picture|painting)|"
    r"imagine\s+(an?\s+)?|visualize|render\s+|design\s+(an?\s+)?(image|logo|banner)|"
    r"show\s+me\s+(an?\s+)?(image|picture|photo))\b",
    re.I,
)

# Detect image editing requests (requires an attached image)
_IMAGE_EDIT_RE = re.compile(
    r"\b(edit\s+(this\s+)?image|modify\s+(this\s+)?image|change\s+(this\s+)?image|"
    r"make\s+(it|this)\s+(look|appear|seem)|add\s+to\s+(this|the)\s+image|"
    r"remove\s+from\s+(this|the)\s+image|transform\s+(this\s+)?image|"
    r"enhance|upscale|colorize|restore)\b",
    re.I,
)


def should_search(query: str) -> bool:
    """Return True if the query would benefit from real-time web search."""
    return bool(_SEARCH_RE.search(query))


def should_x_search(query: str) -> bool:
    """Return True if the query specifically wants X/Twitter content."""
    return bool(_X_RE.search(query))


def is_image_gen_request(query: str) -> bool:
    """Return True if the query is asking IRA to generate an image."""
    return bool(_IMAGE_GEN_RE.search(query))


def is_image_edit_request(query: str) -> bool:
    """Return True if the query is asking IRA to edit an attached image."""
    return bool(_IMAGE_EDIT_RE.search(query))


# ── Web search ────────────────────────────────────────────────────────────────

async def web_search(query: str, max_results: int = 5) -> list[dict]:
    """
    Search the web via DuckDuckGo. Returns list of {title, url, snippet}.
    No API key required. Runs in a thread executor to avoid blocking the loop.
    """
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _ddg_search, query, max_results)
    except Exception as e:
        logger.warning(f"Web search failed: {e}")
        return []


def _ddg_search(query: str, max_results: int) -> list[dict]:
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=max_results))
        return [
            {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
            for r in raw
        ]
    except ImportError:
        logger.warning("duckduckgo-search not installed — run: pip install duckduckgo-search")
        return []
    except Exception as e:
        logger.warning(f"DuckDuckGo search error: {e}")
        return []


# ── X / Twitter search ────────────────────────────────────────────────────────

async def x_search(query: str, max_results: int = 10) -> list[dict]:
    """
    Search X (Twitter) for recent posts. Uses Twitter API v2 if
    TWITTER_BEARER_TOKEN is configured; otherwise falls back to DDG.
    """
    if _TWITTER_BEARER:
        results = await _twitter_api_search(query, max_results)
        if results:
            return results
    return await _twitter_ddg_fallback(query, max_results)


async def _twitter_api_search(query: str, max_results: int) -> list[dict]:
    try:
        import httpx
        headers = {"Authorization": f"Bearer {_TWITTER_BEARER}"}
        params = {
            "query": f"{query} -is:retweet lang:en",
            "max_results": min(max(10, max_results), 100),
            "tweet.fields": "created_at,author_id,text,public_metrics",
            "expansions": "author_id",
            "user.fields": "name,username",
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.twitter.com/2/tweets/search/recent",
                headers=headers,
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

        tweets = data.get("data", [])
        users = {u["id"]: u for u in data.get("includes", {}).get("users", [])}
        results = []
        for t in tweets:
            author = users.get(t.get("author_id", ""), {})
            results.append({
                "text": t["text"],
                "author": author.get("name", "Unknown"),
                "username": f"@{author.get('username', 'unknown')}",
                "created_at": t.get("created_at", ""),
                "url": f"https://twitter.com/{author.get('username','i')}/status/{t['id']}",
                "likes": t.get("public_metrics", {}).get("like_count", 0),
                "retweets": t.get("public_metrics", {}).get("retweet_count", 0),
            })
        return results
    except Exception as e:
        logger.warning(f"Twitter API search failed: {e}")
        return []


async def _twitter_ddg_fallback(query: str, max_results: int) -> list[dict]:
    results = await web_search(f"site:twitter.com OR site:x.com {query}", max_results)
    return [
        {
            "text": r["snippet"],
            "author": r["title"],
            "username": "",
            "url": r["url"],
            "created_at": "",
            "likes": 0,
            "retweets": 0,
        }
        for r in results
    ]


# ── Formatters (for LLM context injection) ───────────────────────────────────

def format_web_results(results: list[dict]) -> str:
    if not results:
        return ""
    lines = [f"**Web search results:**"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. [{r['title']}]({r['url']})\n   {r['snippet'][:200]}")
    return "\n\n".join(lines)


def format_x_results(results: list[dict]) -> str:
    if not results:
        return ""
    lines = ["**Recent X/Twitter posts:**"]
    for r in results[:8]:
        author_str = f"{r['author']} {r['username']}".strip()
        engagement = f" ({r['likes']} likes)" if r.get("likes") else ""
        lines.append(f"• {author_str}{engagement}: {r['text'][:220]}")
    return "\n".join(lines)


async def get_search_context(query: str) -> str:
    """
    Auto-detect search needs and return a formatted context block ready for LLM injection.
    Runs web search + X search in parallel when both are needed.
    """
    need_web = should_search(query)
    need_x = should_x_search(query)

    if not need_web and not need_x:
        return ""

    tasks = []
    if need_web:
        tasks.append(web_search(query, max_results=5))
    if need_x:
        tasks.append(x_search(query, max_results=8))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    parts = []
    idx = 0
    if need_web:
        web_res = results[idx] if not isinstance(results[idx], Exception) else []
        idx += 1
        formatted = format_web_results(web_res)  # type: ignore[arg-type]
        if formatted:
            parts.append(formatted)
    if need_x:
        x_res = results[idx] if not isinstance(results[idx], Exception) else []
        formatted = format_x_results(x_res)  # type: ignore[arg-type]
        if formatted:
            parts.append(formatted)

    return "\n\n".join(parts)
