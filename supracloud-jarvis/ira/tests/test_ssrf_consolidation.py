"""Phase 3 — SSRF guards stay consolidated in utils.net_safety.

All outbound-URL and direct-navigation guards must source their check from
utils.net_safety (getaddrinfo, all A/AAAA records, IPv4-mapped + non-standard
literal handling). No module may reintroduce a divergent copy built on the
IPv4-only socket.gethostbyname. This locks in the Phase 2/3 consolidation so a
future edit can't silently fork the guard again.

It also documents the known residual: the Playwright path in
api/routes/computer_use.py re-resolves the host at page.goto, so a DNS-rebinding
TOCTOU window remains there that IP-pinning cannot close — this must stay
acknowledged in the source.
"""
import os

for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

import inspect
from pathlib import Path

import pytest

IRA = Path(__file__).resolve().parents[1]

# Modules that perform an outbound fetch or a browser navigation and therefore
# must route their SSRF guard through utils.net_safety.
_GUARDED_MODULES = [
    "utils/browser_tools.py",
    "api/routes/computer_use.py",
]


@pytest.mark.parametrize("rel", _GUARDED_MODULES)
def test_guard_sourced_from_net_safety(rel):
    src = (IRA / rel).read_text(encoding="utf-8")
    assert "net_safety" in src, f"{rel} must import its SSRF guard from utils.net_safety"
    assert "gethostbyname" not in src, f"{rel} must not keep an IPv4-only resolver"


def test_browser_tools_check_url_is_net_safety():
    import utils.browser_tools as bt
    import utils.net_safety as ns

    assert bt.check_url is ns.check_url


def test_playwright_rebinding_residual_is_documented():
    src = (IRA / "api/routes/computer_use.py").read_text(encoding="utf-8")
    assert "residual" in src.lower() and "rebind" in src.lower(), (
        "the Playwright re-resolution residual must stay documented in computer_use.py"
    )
