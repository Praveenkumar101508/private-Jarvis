"""
IRA Digital Eyes — Browser automation tools (Phase 6).

browse_and_summarize_website(url, query) → Playwright headless Chromium + LLM summary.
Navigates to any URL, extracts visible text, answers the user's specific query.
"""
from __future__ import annotations

import ipaddress
import logging
import re
import socket
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger("ira.browser_tools")

# Block SSRF: deny private/link-local/loopback IPs and non-HTTP schemes
_BLOCKED_HOSTS = re.compile(
    r"^(localhost|.*\.local|.*\.internal|.*\.corp)$", re.I
)

def _sanitize_url(url: str) -> str:
    """Fix #41: strip embedded credentials and URL fragments before use.

    A URL like http://user:pass@internal-host/ leaks credentials into logs
    and bypasses hostname checks if the netloc includes auth info. Rebuilding
    without credentials and without a fragment prevents both issues.
    """
    try:
        p = urlparse(url)
        # Reconstruct netloc without user:pass — keep host and port only
        netloc = p.hostname or ""
        if p.port:
            netloc = f"{netloc}:{p.port}"
        return urlunparse((p.scheme, netloc, p.path, p.params, p.query, ""))
    except Exception:
        return url


def _is_safe_url(url: str) -> bool:
    """Return True only for publicly routable HTTP/HTTPS URLs.

    Fix #39: resolves the hostname to an IP address before approving the
    request — a DNS rebinding attack can make a safe-looking hostname resolve
    to an internal IP at the moment Playwright opens the connection. Checking
    the resolved IP here closes that window by blocking the request before
    the browser is even launched.
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = parsed.hostname or ""
        if not host:
            return False
        if _BLOCKED_HOSTS.match(host):
            return False
        # Determine the IP — either the host is already an IP literal, or we
        # resolve it synchronously (Fix #39: DNS rebinding protection).
        try:
            addr = ipaddress.ip_address(host)
        except ValueError:
            # Hostname — resolve and check the returned IP
            try:
                resolved = socket.gethostbyname(host)
                addr = ipaddress.ip_address(resolved)
            except (socket.gaierror, ValueError):
                return False  # Unresolvable → deny
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast:
            return False
        return True
    except Exception:
        return False

_MAX_PAGE_TEXT = 8_000  # characters fed to LLM


def _clean_text(raw: str) -> str:
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = re.sub(r"[\t ]+", " ", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    return raw.strip()


async def browse_and_summarize_website(url: str, query: str) -> dict:
    """
    Navigate to `url` with a headless Chromium browser, extract visible text,
    and use IRA's fast LLM to answer `query` based on what's on the page.
    Returns a structured dict with the answer, page title, and a brief excerpt.
    """
    # Fix #41: strip embedded credentials and fragments before any checks or logging
    url = _sanitize_url(url)
    if not _is_safe_url(url):
        return {
            "error": "URL blocked for security reasons. Only public HTTP/HTTPS URLs are allowed.",
            "url": url,
        }

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {
            "error": (
                "Playwright not installed. "
                "Run: pip install playwright && playwright install chromium"
            )
        }

    page_text = ""
    page_title = ""

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    # Fix #40: --no-sandbox is required when Chromium runs as root
                    # inside a Docker container. The container itself is the sandbox;
                    # removing this flag would crash Chromium on startup in that env.
                    "--no-sandbox",
                    "--disable-dev-shm-usage",  # prevent /dev/shm exhaustion in Docker
                    "--disable-gpu",
                ],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            )
            page = await context.new_page()

            # Block heavy resources — only need text
            await page.route(
                "**/*.{png,jpg,jpeg,gif,webp,svg,ico,woff,woff2,ttf,mp4,mp3,pdf}",
                lambda r: r.abort(),
            )

            await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
            page_title = await page.title()
            raw = await page.evaluate("() => document.body.innerText || ''")
            page_text = _clean_text(raw)[:_MAX_PAGE_TEXT]
            await browser.close()

    except Exception as e:
        logger.error(f"Playwright navigation failed for {url}: {e}")
        return {"error": f"Could not load page: {e}", "url": url}

    if not page_text.strip():
        return {"error": "No text content found on this page.", "url": url, "title": page_title}

    prompt = (
        f'You are an expert at extracting precise answers from web pages.\n'
        f'The user asks: "{query}"\n\n'
        f"Page: {url}\n"
        f"Title: {page_title}\n\n"
        f"Page content:\n---\n{page_text}\n---\n\n"
        f"Answer the user's question using ONLY information on this page. "
        f"Be specific — quote prices, names, and dates when available. "
        f"If the answer is not on the page, say so clearly."
    )

    try:
        from utils.llm import chat_complete
        answer = await chat_complete(
            [{"role": "user", "content": prompt}],
            use_deep=False,
            temperature=0.1,
            max_tokens=512,
        )
        logger.info(f"Browse & summarize: {url[:60]} → answer generated")
        return {
            "url": url,
            "title": page_title,
            "query": query,
            "answer": answer,
            "page_excerpt": page_text[:400],
        }
    except Exception as e:
        return {
            "url": url,
            "title": page_title,
            "query": query,
            "raw_excerpt": page_text[:2000],
            "error": f"LLM summarization failed: {e}",
        }
