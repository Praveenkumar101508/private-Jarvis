"""
ira/utils/net_safety.py — single source of truth for outbound URL safety (SSRF).

Replaces the two divergent guards:
  - utils/url_safety.py  (weak: socket.gethostbyname → IPv4-only, single A record)
  - channels/guard.py    (strong, but separate copy → drift)

Hardening over the old url_safety.py:
  * getaddrinfo (ALL records, IPv4 + IPv6) instead of gethostbyname (one IPv4 record).
  * Rejects IPv4-mapped IPv6 loopback/private (e.g. ::ffff:127.0.0.1) — the old
    guard let these through.
  * Rejects non-standard IP literal encodings (decimal 2130706433, hex 0x7f000001,
    octal 0177.0.0.1) that resolvers accept but ipaddress.ip_address() rejects.
  * Blocks loopback, RFC1918 private, link-local (169.254 cloud metadata),
    unique-local IPv6, reserved, unspecified (0.0.0.0/::), and multicast — via the
    ipaddress .is_* predicates, so new reserved ranges are covered automatically.

KNOWN RESIDUAL — TOCTOU / DNS rebinding: is_safe_url() validates the hostname's
resolved IPs, but the HTTP client re-resolves at connect time and could rebind to
an internal IP. For high-risk fetches, resolve once and connect to the pinned IP
(see resolve_pinned() below) or front the fetch with a filtering agent.

Interfaces preserved for drop-in replacement:
  is_safe_url(url) -> bool                     (was utils/url_safety.is_safe_url)
  check_url(url, *, resolve_fn) -> (bool, str) (was channels/guard.is_public_url)
  is_safe_query(text) -> (bool, str)           (was channels/guard.is_safe_query)
  guard_outbound(url=, query=, resolve_fn=) -> Optional[str]
"""
from __future__ import annotations

import ipaddress
import logging
import re
import socket
from typing import Callable, Optional
from urllib.parse import urlparse

logger = logging.getLogger("ira.net_safety")

_BLOCKED_HOST_SUFFIXES = (".local", ".internal", ".corp", ".lan", ".localdomain")
_DOTTED_QUAD_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")

# Secret / credential smuggling markers (kept from channels/guard.py).
_SECRET_RE = re.compile(
    r"(BEGIN [A-Z ]*PRIVATE KEY|api[_-]?key\s*[:=]|password\s*[:=]|passwd\s*[:=]"
    r"|secret\s*[:=]|aws_secret|bearer\s+[A-Za-z0-9._\-]{20,})",
    re.IGNORECASE,
)
_LOCAL_PATH_RE = re.compile(r"(^|\s)(/etc/|/var/|/root/|/home/|[A-Za-z]:\\|file://)")


def _ip_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for any non-publicly-routable address. Unwraps IPv4-mapped IPv6."""
    # IPv4-mapped IPv6 (::ffff:127.0.0.1) — check the embedded v4 too.
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_unspecified
        or ip.is_multicast
    )


def _looks_like_nonstandard_ip_literal(host: str) -> bool:
    """True for decimal/octal/hex single-integer IPv4 forms resolvers accept."""
    s = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    s = s.lower()
    try:
        if s.startswith("0x"):
            int(s, 16)
        elif s.startswith("0") and s != "0":
            int(s, 8)
        else:
            int(s, 10)
        return True
    except ValueError:
        return False


def _resolve_all(host: str) -> list[str]:
    """All IPv4 + IPv6 addresses for host (deduped)."""
    infos = socket.getaddrinfo(host, None)
    return sorted({info[4][0] for info in infos})


def check_url(
    url: str, *, resolve_fn: Optional[Callable[[str], list[str]]] = None
) -> tuple[bool, str]:
    """Validate a URL is http(s) to a publicly-routable host. Returns (ok, reason)."""
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https"):
        return False, f"only http(s) URLs allowed (got scheme {parsed.scheme or 'none'!r})"
    host = (parsed.hostname or "").lower()
    if not host:
        return False, "URL has no host"
    if host == "localhost" or host.endswith(_BLOCKED_HOST_SUFFIXES):
        return False, f"refusing internal host ({host})"

    # Is it a standard IP literal (dotted-quad or bracketed/bare IPv6)?
    candidate = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    try:
        ip = ipaddress.ip_address(candidate)
        if _ip_is_blocked(ip):
            return False, f"refusing private/reserved IP ({candidate})"
        return True, ""
    except ValueError:
        pass  # not a standard literal — fall through

    # Non-standard IP literal encodings (decimal/octal/hex) → reject outright.
    if _looks_like_nonstandard_ip_literal(host):
        return False, f"refusing non-standard IP literal ({host})"

    # Ordinary hostname → resolve ALL records; reject if ANY is non-routable.
    resolver = resolve_fn or _resolve_all
    try:
        addrs = resolver(host)
    except OSError:
        return False, f"host unresolvable ({host})"
    if not addrs:
        return False, f"host unresolvable ({host})"
    for addr in addrs:
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if _ip_is_blocked(ip):
            return False, f"host ({host}) resolves to a private address ({addr})"
    return True, ""


def is_safe_url(url: str) -> bool:
    """Bool drop-in for utils/url_safety.is_safe_url. Logs the reason on block."""
    ok, reason = check_url(url)
    if not ok:
        logger.warning("URL blocked — %s: %r", reason, url)
    return ok


def is_safe_query(text: str) -> tuple[bool, str]:
    if _SECRET_RE.search(text or ""):
        return False, "query appears to contain a secret/credential — not sent outbound"
    if _LOCAL_PATH_RE.search(text or ""):
        return False, "query appears to contain a local file path — not sent outbound"
    return True, ""


def guard_outbound(
    *,
    url: Optional[str] = None,
    query: Optional[str] = None,
    resolve_fn: Optional[Callable[[str], list[str]]] = None,
) -> Optional[str]:
    """Return a refusal reason if this outbound request must be blocked, else None."""
    if url is not None:
        ok, reason = check_url(url, resolve_fn=resolve_fn)
        if not ok:
            return f"Blocked: {reason}."
    if query is not None:
        ok, reason = is_safe_query(query)
        if not ok:
            return f"Blocked: {reason}."
    return None


def resolve_pinned(host: str) -> Optional[str]:
    """Resolve host and return a single safe IP to PIN the connection to.

    Closes the TOCTOU gap: validate here, then make the HTTP client connect to the
    returned IP (passing Host: header) so the name can't rebind between check and
    connect. Returns None if the host has no safe address.

    NOTE: there is no in-tree caller today — IRA does not directly fetch arbitrary
    user/content URLs with its own HTTP client. Arbitrary-URL fetching is delegated
    to trusted self-hosted services (Crawl4AI, SearXNG) that do their own DNS
    resolution, and the one direct-navigation path (Playwright in
    api/routes/computer_use.py) re-resolves internally and can't be pinned. This is
    kept for any future direct fetch+connect caller, which should pin via this fn.
    """
    try:
        addrs = _resolve_all(host)
    except OSError:
        return None
    for addr in addrs:
        try:
            if not _ip_is_blocked(ipaddress.ip_address(addr)):
                return addr
        except ValueError:
            continue
    return None


__all__ = [
    "is_safe_url",
    "check_url",
    "is_safe_query",
    "guard_outbound",
    "resolve_pinned",
]
