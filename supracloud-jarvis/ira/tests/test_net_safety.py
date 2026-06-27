"""Proves the consolidated guard blocks the bypasses the old url_safety.py missed.

Converted from the standalone proof script into pytest assertions so a regression
that lets any of these through (a "leak") FAILS the suite rather than just printing.
Covers the four encodings the old socket.gethostbyname/IPv4-only guard let through:
IPv4-mapped IPv6, decimal/hex IP literals, and the unspecified address 0.0.0.0.
"""
import pytest

from utils.net_safety import check_url, is_safe_url


# Deterministic offline resolver for the DNS-rebinding hostname cases.
def fake_resolve(host):
    return {
        "evil.example.com": ["127.0.0.1"],            # rebind to loopback
        "evil6.example.com": ["::1"],                 # rebind to IPv6 loopback
        "metadata.example.com": ["169.254.169.254"],  # cloud metadata
        "good.example.com": ["93.184.216.34"],        # real public IP
    }.get(host, [])


# Literals / schemes that must be blocked without any DNS resolution.
BLOCK = [
    "http://127.0.0.1/",              # loopback literal
    "http://[::ffff:127.0.0.1]/",     # IPv4-mapped IPv6 loopback  <-- old guard MISSED
    "http://2130706433/",             # decimal-encoded 127.0.0.1  <-- old guard MISSED
    "http://0x7f000001/",             # hex-encoded 127.0.0.1      <-- old guard MISSED
    "http://169.254.169.254/latest/", # AWS/GCP metadata
    "http://10.0.0.5/",               # RFC1918
    "http://192.168.1.1/",            # RFC1918
    "http://0.0.0.0/",                # unspecified                <-- old guard MISSED
    "http://[::1]/",                  # IPv6 loopback
    "file:///etc/passwd",             # non-http scheme
    "ftp://example.com/",             # non-http scheme
    "http://localhost/",              # internal hostname
    "http://db.internal/",            # internal suffix
]

# Public-looking hostnames that resolve to internal addresses (DNS rebinding).
BLOCK_DNS = [
    "http://evil.example.com/",
    "http://evil6.example.com/",
    "http://metadata.example.com/",
]

# Genuinely public destinations that must be allowed.
ALLOW = [
    "https://good.example.com/",
    "http://93.184.216.34/",
]


@pytest.mark.parametrize("url", BLOCK)
def test_block_literals_and_schemes(url):
    ok, reason = check_url(url)
    assert not ok, f"LEAK: {url} was allowed"
    assert reason, "a blocked URL must carry a refusal reason"
    # is_safe_url is the bool drop-in for the old url_safety.is_safe_url callers.
    assert is_safe_url(url) is False


@pytest.mark.parametrize("url", BLOCK_DNS)
def test_block_dns_rebinding(url):
    ok, reason = check_url(url, resolve_fn=fake_resolve)
    assert not ok, f"LEAK: {url} resolved to a private address but was allowed"
    assert reason


@pytest.mark.parametrize("url", ALLOW)
def test_allow_public(url):
    ok, reason = check_url(url, resolve_fn=fake_resolve)
    assert ok, f"FALSE-BLOCK: {url} -> {reason}"


def test_unresolvable_host_is_denied():
    # Empty resolution (unknown host) must fail closed, not open.
    ok, _ = check_url("http://unknown.example.org/", resolve_fn=lambda h: [])
    assert not ok
