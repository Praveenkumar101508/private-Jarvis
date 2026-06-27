"""Phase 2 — the browser tool must use the consolidated net_safety SSRF guard.

browser_tools shipped its own ``_is_safe_url`` built on ``socket.gethostbyname``
(IPv4-only, single record, no IPv4-mapped-IPv6 unwrap), so ``http://[::ffff:127.0.0.1]/``
and non-standard IP literals slipped through. The hardened ``utils.net_safety.check_url``
already rejects all of these, so browse_and_summarize_website must route through it
and block these URLs *before* a browser is ever launched.
"""
import os

for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

import asyncio

import pytest

from utils.browser_tools import browse_and_summarize_website


def _is_blocked(result: dict) -> bool:
    err = (result.get("error") or "").lower()
    return "block" in err or "refus" in err or "not allowed" in err


@pytest.mark.parametrize("url", [
    "http://[::ffff:127.0.0.1]/",        # IPv4-mapped IPv6 loopback — old bypass
    "http://0x7f000001/",                # hex-encoded 127.0.0.1
    "http://2130706433/",                # decimal-encoded 127.0.0.1
    "http://127.0.0.1/",                 # plain loopback
    "http://localhost/admin",            # internal name
    "http://169.254.169.254/latest/",    # cloud metadata link-local
    "ftp://example.com/",                # non-http(s) scheme
])
def test_browse_blocks_ssrf_urls(url):
    result = asyncio.run(browse_and_summarize_website(url, "what is here"))
    assert _is_blocked(result), f"expected {url!r} to be blocked, got {result!r}"


def test_browser_tools_delegates_to_net_safety():
    """No divergent SSRF copy: the browser tool must use the consolidated guard.

    ``socket.gethostbyname`` is IPv4-only and resolves a single record, so a
    divergent copy can miss AAAA-only rebinding that ``net_safety.check_url``
    (getaddrinfo, all records) catches. Enforce delegation structurally.
    """
    import inspect
    import utils.browser_tools as bt

    src = inspect.getsource(bt)
    assert "net_safety" in src, "browser_tools must route through utils.net_safety"
    assert "gethostbyname" not in src, "browser_tools must not keep an IPv4-only resolver"
