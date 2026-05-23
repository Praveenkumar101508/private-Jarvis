"""
IRA Real-Time Search Tools — Web Search + X (Twitter) Search.

Web search uses DuckDuckGo (no API key required, async wrapper).
X/Twitter search delegates to utils.x_search which supports:
  - Official X API v2 (TWITTER_BEARER_TOKEN)
  - Cheap fallback API (X_FALLBACK_API_KEY + X_FALLBACK_API_URL)
  - DuckDuckGo site:x.com last-resort fallback

get_search_context() returns (context_str, meta) where meta carries
  used_live_x: bool — set True when real X API results were fetched,
  which triggers the "Live from X" badge in the frontend.
"""

from __future__ import annotations

import asyncio
import logging
import re

logger = logging.getLogger("ira.search")

# Detect queries that benefit from real-time web search
_SEARCH_RE = re.compile(
    r"\b(today|yesterday|this week|this month|current|latest|recent|breaking|"
    r"news|now|2024|2025|2026|price of|stock price|weather|who is|"
    r"what is happening|just announced|just released|search for|look up|find|"
    r"trending|viral|x\.com|twitter|tweet)\b",
    re.I,
)

# Detect queries specifically about X/Twitter content or celebrity/country sentiment
_X_RE = re.compile(
    r"\b(twitter|x\.com|tweet|trending on x|"
    r"people (are |were )?saying|everyone.*saying|social.*opinion|viral|"
    r"what.*bollywood|what.*celebrities|what.*people think|public opinion|"
    r"elon musk|elon says?|trump says?|trump tweet|modi says?|modi tweet|"
    r"celebrity opinion|actor (said?|think|tweet)|"
    r"india.*think|uk.*think|us.*think|brazil.*think)\b",
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
    return bool(_SEARCH_RE.search(query))


def should_x_search(query: str) -> bool:
    return bool(_X_RE.search(query))


def is_image_gen_request(query: str) -> bool:
    return bool(_IMAGE_GEN_RE.search(query))


def is_image_edit_request(query: str) -> bool:
    return bool(_IMAGE_EDIT_RE.search(query))


# ── Web search ────────────────────────────────────────────────────────────────

async def web_search(query: str, max_results: int = 5) -> list[dict]:
    """
    Search the web via DuckDuckGo. Returns list of {title, url, snippet}.
    Runs in a thread executor to avoid blocking the event loop.
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
    Country-aware X search. Delegates to utils.x_search.smart_x_search().
    Returns results as plain dicts (legacy format for callers that don't need meta).
    """
    from utils.x_search import smart_x_search
    results, _used_live, _cc = await smart_x_search(query, max_results)
    return [r._asdict() for r in results]


# ── Formatters ────────────────────────────────────────────────────────────────

def format_web_results(results: list[dict]) -> str:
    if not results:
        return ""
    lines = ["**Web search results:**"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. [{r['title']}]({r['url']})\n   {r['snippet'][:200]}")
    return "\n\n".join(lines)


def format_x_results(results: list[dict]) -> str:
    if not results:
        return ""
    lines = ["**Recent X/Twitter posts:**"]
    for r in results[:8]:
        author_str = f"{r.get('author', '')} {r.get('username', '')}".strip()
        engagement = f" ({r['likes']} likes)" if r.get("likes") else ""
        lines.append(f"• {author_str}{engagement}: {r.get('text', '')[:220]}")
    return "\n".join(lines)


# ── Combined search context (used by chat.py) ─────────────────────────────────

async def get_search_context(query: str) -> tuple[str, dict]:
    """
    Auto-detect search needs and return (context_str, meta).

    meta keys:
      used_live_x: bool  — True if real X API results were fetched
      x_count: int       — number of X results
      web_count: int     — number of web results

    Runs web search + X search in parallel when both are needed.
    """
    need_web = should_search(query)
    need_x = should_x_search(query)

    meta: dict = {"used_live_x": False, "x_count": 0, "web_count": 0}

    if not need_web and not need_x:
        return "", meta

    from utils.x_search import smart_x_search, format_x_results as _fmt_x

    parts: list[str] = []

    if need_web and need_x:
        web_task = asyncio.create_task(web_search(query, max_results=5))
        x_task = asyncio.create_task(smart_x_search(query, max_results=10))
        web_res, x_tuple = await asyncio.gather(web_task, x_task, return_exceptions=True)

        if not isinstance(web_res, Exception) and web_res:
            meta["web_count"] = len(web_res)  # type: ignore[arg-type]
            formatted = format_web_results(web_res)  # type: ignore[arg-type]
            if formatted:
                parts.append(formatted)

        if not isinstance(x_tuple, Exception):
            x_results, used_live, cc = x_tuple  # type: ignore[misc]
            meta["used_live_x"] = used_live
            meta["x_count"] = len(x_results)
            formatted = _fmt_x(x_results, used_live_api=used_live, country_code=cc)
            if formatted:
                parts.append(formatted)

    elif need_web:
        web_res = await web_search(query, max_results=5)
        meta["web_count"] = len(web_res)
        formatted = format_web_results(web_res)
        if formatted:
            parts.append(formatted)

    else:  # need_x only
        x_results, used_live, cc = await smart_x_search(query, max_results=10)
        meta["used_live_x"] = used_live
        meta["x_count"] = len(x_results)
        formatted = _fmt_x(x_results, used_live_api=used_live, country_code=cc)
        if formatted:
            parts.append(formatted)

    return "\n\n".join(parts), meta
