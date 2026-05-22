"""
IRA Digital Eyes — Browser automation tools (Phase 6).

browse_and_summarize_website(url, query) → Playwright headless Chromium + LLM summary.
Navigates to any URL, extracts visible text, answers the user's specific query.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger("ira.browser_tools")

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
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
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
