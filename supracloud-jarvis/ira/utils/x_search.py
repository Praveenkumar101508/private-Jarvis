"""
Enhanced X/Twitter search with country awareness, celebrity detection,
official API v2 support, and a cheap third-party fallback API.

Priority chain:
  1. Official X API v2 (TWITTER_BEARER_TOKEN) — best quality, 7-day recent search
  2. twitterapi.io (X_FALLBACK_API_KEY) — cheap alternative, no rate-limit issues
  3. DuckDuckGo site:x.com — free, limited quality, always available

Country detection automatically enriches queries with language operators
(e.g., India → lang:hi OR lang:en) so results are relevant to the right market.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import NamedTuple

logger = logging.getLogger("ira.x_search")

# Fix L4: API credentials are now read lazily from get_settings() inside each
# function — not at module import time.  This matches Fix #58 (config anti-pattern):
# module-level os.getenv() reads stale values when env vars are set after import.

# ── Country / Language detection ──────────────────────────────────────────────
# Each tuple: (compiled regex, ISO 3166-1 alpha-2, space-separated lang codes)
_COUNTRY_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(
        r"\b(india|indian|bollywood|modi|bjp|congress party|ipl|desi|"
        r"delhi|mumbai|hyderabad|bangalore|bengaluru|chennai|kolkata|"
        r"rupee|inr|hindustan|bharat|cricket india)\b", re.I,
    ), "IN", "hi en"),
    (re.compile(
        r"\b(usa|united states|america|american|trump|biden|harris|"
        r"democrat|republican|washington dc|new york|california|nasdaq|nyse|wall street)\b", re.I,
    ), "US", "en"),
    (re.compile(
        r"\b(brazil|brasil|brazilian|lula|bolsonaro|s[aã]o paulo|"
        r"rio de janeiro|reais|brl|copa)\b", re.I,
    ), "BR", "pt"),
    (re.compile(
        r"\b(uk|britain|british|england|scotland|wales|london|"
        r"boris|sunak|rishi|parliament|gbp|pound sterling|premier league)\b", re.I,
    ), "GB", "en"),
    (re.compile(
        r"\b(pakistan|pakistani|lahore|karachi|islamabad|imran khan|urdu|psl)\b", re.I,
    ), "PK", "ur en"),
    (re.compile(
        r"\b(germany|german|deutsch|berlin|munich|hamburg|scholz|bundesliga)\b", re.I,
    ), "DE", "de"),
    (re.compile(
        r"\b(france|french|paris|macron|lyon|marseille|ligue 1)\b", re.I,
    ), "FR", "fr"),
    (re.compile(
        r"\b(japan|japanese|tokyo|osaka|nagoya|yen|jpy|anime|manga|nintendo|sony japan)\b", re.I,
    ), "JP", "ja"),
    (re.compile(
        r"\b(korea|korean|seoul|kpop|k-pop|webtoon|bts|blackpink|won|krw)\b", re.I,
    ), "KR", "ko"),
    (re.compile(
        r"\b(australia|australian|sydney|melbourne|brisbane|aud|afl|aussie)\b", re.I,
    ), "AU", "en"),
    (re.compile(
        r"\b(nigeria|nigerian|lagos|abuja|naira|ngn|nollywood)\b", re.I,
    ), "NG", "en"),
    (re.compile(
        r"\b(canada|canadian|toronto|vancouver|ottawa|trudeau|cad)\b", re.I,
    ), "CA", "en"),
    (re.compile(
        r"\b(spain|spanish|madrid|barcelona|la liga|ibex)\b", re.I,
    ), "ES", "es"),
    (re.compile(
        r"\b(italy|italian|rome|milan|naples|serie a|lira|eur italy)\b", re.I,
    ), "IT", "it"),
    (re.compile(
        r"\b(china|chinese|beijing|shanghai|shenzhen|yuan|cny|alibaba|tencent|baidu)\b", re.I,
    ), "CN", "zh"),
]

# Fix L10: removed hardcoded celebrity/politician names (elon musk, trump, modi, etc.)
# from _CELEBRITY_RE.  Hard-coding individual names is fragile (new public figures are
# missed; names clash with innocent words like "elon" as a first name in other contexts).
# Country patterns in _COUNTRY_PATTERNS already route country-specific leader queries
# (e.g. "modi" → India, "trump" → US).  Role-based terms are sufficient here.
_CELEBRITY_RE = re.compile(
    r"\b(what (is|are|did|does) .{0,40} (saying?|think|tweet|post)|"
    r"opinion of|according to|celebrity|actor|actress|singer|"
    r"ceo|founder|politician|president|prime minister|senator)\b",
    re.I,
)

_CLEAN_RE = re.compile(
    r"\b(on twitter|on x\.com|on x|tweet(s)? about|trending on x|"
    r"people (are |were )?saying|what is trending|latest tweets?)\b",
    re.I,
)


# ── Result type ───────────────────────────────────────────────────────────────

class XResult(NamedTuple):
    text: str
    author: str
    username: str
    created_at: str
    url: str
    likes: int
    retweets: int
    country_code: str = ""


# ── Country / celebrity detection ─────────────────────────────────────────────

def detect_country(query: str) -> tuple[str | None, str | None]:
    """Return (country_code, space-sep lang codes) from query text, or (None, None)."""
    for pattern, cc, langs in _COUNTRY_PATTERNS:
        if pattern.search(query):
            return cc, langs
    return None, None


def is_celebrity_query(query: str) -> bool:
    return bool(_CELEBRITY_RE.search(query))


def _build_x_query(query: str, country_code: str | None, langs: str | None) -> str:
    """Build X API v2 query with language operators."""
    clean = _CLEAN_RE.sub(" ", query).strip()
    clean = " ".join(clean.split())[:300]

    parts = [clean, "-is:retweet"]
    if langs:
        lang_list = langs.split()[:2]
        if len(lang_list) > 1:
            parts.append(f"(lang:{lang_list[0]} OR lang:{lang_list[1]})")
        else:
            parts.append(f"lang:{lang_list[0]}")
    return " ".join(parts)


# ── Official X API v2 ─────────────────────────────────────────────────────────

async def _official_search(
    query: str, max_results: int, country_code: str | None, langs: str | None,
) -> list[XResult]:
    from config import get_settings
    bearer_token = get_settings().twitter_bearer_token  # Fix L4: lazy read
    if not bearer_token:
        return []

    x_query = _build_x_query(query, country_code, langs)
    try:
        import httpx
        params = {
            "query": x_query,
            "max_results": min(max(10, max_results), 100),
            "tweet.fields": "created_at,author_id,text,public_metrics",
            "expansions": "author_id",
            "user.fields": "name,username",
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.twitter.com/2/tweets/search/recent",
                headers={"Authorization": f"Bearer {bearer_token}"},
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

        tweets = data.get("data", [])
        users = {u["id"]: u for u in data.get("includes", {}).get("users", [])}
        results: list[XResult] = []
        for t in tweets:
            user = users.get(t.get("author_id", ""), {})
            uname = user.get("username", "unknown")
            m = t.get("public_metrics", {})
            results.append(XResult(
                text=t["text"],
                author=user.get("name", "Unknown"),
                username=f"@{uname}",
                created_at=t.get("created_at", ""),
                url=f"https://x.com/{uname}/status/{t['id']}",
                likes=m.get("like_count", 0),
                retweets=m.get("retweet_count", 0),
                country_code=country_code or "",
            ))
        logger.info(f"Official X API: {len(results)} results, query='{x_query[:60]}'")
        return results
    except Exception as e:
        logger.warning(f"Official X API failed: {e}")
        return []


# ── twitterapi.io / compatible fallback ───────────────────────────────────────

async def _fallback_search(
    query: str, max_results: int, country_code: str | None, langs: str | None,
) -> list[XResult]:
    """
    Call the configured cheap X API provider (default: twitterapi.io).
    Set X_FALLBACK_API_URL and X_FALLBACK_API_KEY in .env to activate.
    """
    from config import get_settings
    cfg = get_settings()
    fallback_key = cfg.x_fallback_api_key          # Fix L4: lazy read
    fallback_url = cfg.x_fallback_api_url.rstrip("/")
    if not fallback_key:
        return []

    x_query = _build_x_query(query, country_code, langs)
    if country_code:
        x_query += f" place_country:{country_code}"

    try:
        import httpx
        params = {"query": x_query, "queryType": "Latest", "count": min(max_results, 20)}
        headers = {"X-API-Key": fallback_key}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{fallback_url}/twitter/tweet/advanced_search",
                params=params,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        results: list[XResult] = []
        for t in data.get("tweets", []):
            author = t.get("author", {})
            uname = author.get("userName", "unknown")
            results.append(XResult(
                text=t.get("text", ""),
                author=author.get("name", "Unknown"),
                username=f"@{uname}",
                created_at=t.get("createdAt", ""),
                url=f"https://x.com/{uname}/status/{t.get('id', '')}",
                likes=t.get("likeCount", 0),
                retweets=t.get("retweetCount", 0),
                country_code=country_code or "",
            ))
        logger.info(f"Fallback X API ({fallback_url}): {len(results)} results")
        return results
    except Exception as e:
        logger.warning(f"Fallback X API failed: {e}")
        return []


# ── DuckDuckGo last-resort fallback ──────────────────────────────────────────

async def _ddg_x_search(query: str, max_results: int) -> list[XResult]:
    try:
        from utils.search_tools import web_search
        ddg_results = await web_search(f"site:x.com {query}", max_results)
        return [
            XResult(
                text=r["snippet"],
                author=r["title"],
                username="",
                created_at="",
                url=r["url"],
                likes=0,
                retweets=0,
                country_code="",
            )
            for r in ddg_results
        ]
    except Exception as e:
        logger.warning(f"DDG X fallback failed: {e}")
        return []


# ── Public API ────────────────────────────────────────────────────────────────

async def smart_x_search(
    query: str,
    max_results: int = 10,
) -> tuple[list[XResult], bool, str]:
    """
    Country-aware X search using the best available method.

    Returns: (results, used_live_api, detected_country_code)
      used_live_api — True if official X API or paid fallback was used (not DDG).
    """
    country_code, langs = detect_country(query)

    results = await _official_search(query, max_results, country_code, langs)
    if results:
        return results, True, country_code or ""

    results = await _fallback_search(query, max_results, country_code, langs)
    if results:
        return results, True, country_code or ""

    results = await _ddg_x_search(query, max_results)
    return results, False, country_code or ""


def format_x_results(
    results: list[XResult],
    used_live_api: bool = False,
    country_code: str = "",
) -> str:
    if not results:
        return ""

    country_label = f" [{country_code}]" if country_code else ""
    source = "Live X posts" if used_live_api else "X mentions (web search)"
    lines = [f"**{source}{country_label}:**"]

    for r in results[:8]:
        author_str = f"{r.author} {r.username}".strip() if r.username else r.author
        engagement = ""
        if r.likes:
            engagement += f" ♥{r.likes}"
        if r.retweets:
            engagement += f" ↺{r.retweets}"
        text_preview = r.text[:240].replace("\n", " ")
        lines.append(f"• {author_str}{engagement}: {text_preview}")

    return "\n".join(lines)
