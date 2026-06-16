"""
ira/channels/guard.py — public-only guardrail for outbound web research.

The value rule: read PUBLIC sources only; never carry a private/internal target,
local file contents, client documents, or secrets outward. This guard runs before
any fetch:
  - URLs must be http(s) to a PUBLIC host (no localhost / 127.x / RFC1918 / *.local /
    file:// — i.e. nothing internal).
  - Queries must not look like smuggled private content (PEM keys, credentials,
    local filesystem paths).

guard_outbound() returns a refusal string when the request must be blocked, else None.
"""
from __future__ import annotations

import ipaddress
import re
import socket
from typing import Callable, Optional
from urllib.parse import urlparse

_PRIVATE_HOST_SUFFIXES = (".local", ".internal", ".lan", ".localdomain")

# A bare dotted-quad / bracketed-IPv6 hostname, e.g. "127.0.0.1" or "[::1]".
# Anything else that *isn't* this shape but still parses as an ip_address
# (decimal, octal, hex forms like "0x7f000001" or "2130706433") is an
# alternate encoding browsers/resolvers accept but ipaddress.ip_address()
# does for - so we reject any non-dotted-quad literal outright rather than
# letting it fall through as "looks like a domain, must be public".
_DOTTED_QUAD_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")


def _looks_like_ip_literal(host: str) -> bool:
    """True if host is some IP-address encoding, dotted-quad or not."""
    if _DOTTED_QUAD_RE.match(host):
        return True
    candidate = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    try:
        ipaddress.ip_address(candidate)
        return True
    except ValueError:
        pass
    # Decimal / octal / hex single-integer IPv4 literals (e.g. "2130706433",
    # "0x7f000001", "017700000001") that ipaddress.ip_address() rejects but
    # socket.inet_aton-style parsers / browsers will happily resolve.
    stripped = candidate.lower()
    try:
        if stripped.startswith("0x"):
            int(stripped, 16)
        elif stripped.startswith("0") and stripped not in ("0",):
            int(stripped, 8)
        else:
            int(stripped, 10)
        return True
    except ValueError:
        return False

# Markers that suggest a secret/credential is being smuggled into an outbound query.
_SECRET_RE = re.compile(
    r"(BEGIN [A-Z ]*PRIVATE KEY|api[_-]?key\s*[:=]|password\s*[:=]|passwd\s*[:=]"
    r"|secret\s*[:=]|aws_secret|bearer\s+[A-Za-z0-9._\-]{20,})",
    re.IGNORECASE,
)
# Local filesystem paths / file scheme that should never be sent to a web backend.
_LOCAL_PATH_RE = re.compile(r"(^|\s)(/etc/|/var/|/root/|/home/|[A-Za-z]:\\|file://)")


def _is_private_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified


def _is_private_host(host: str) -> bool:
    host = (host or "").lower()
    if host == "localhost" or host.endswith(_PRIVATE_HOST_SUFFIXES):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return _is_private_ip(ip)
    except ValueError:
        return False  # an ordinary public domain name


def is_public_url(
    url: str, *, resolve_fn: Optional[Callable[[str], list[str]]] = None
) -> tuple[bool, str]:
    """Validate a URL is http(s) to a public, non-private destination.

    Checks the hostname string itself, rejects non-dotted-quad IP literal
    encodings outright (decimal/octal/hex forms used to smuggle a private
    address past naive string checks), and — to defend against DNS
    rebinding — resolves ordinary hostnames and rejects the URL if *any*
    resolved address is private/loopback/link-local/reserved/unspecified.
    """
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https"):
        return False, f"only http(s) URLs may be fetched (got scheme {parsed.scheme or 'none'!r})"
    host = parsed.hostname or ""
    if not host:
        return False, "URL has no host"
    if _is_private_host(host):
        return False, f"refusing to fetch a private/internal host ({host})"

    is_dotted_quad_or_ipv6 = False
    try:
        candidate = host[1:-1] if host.startswith("[") and host.endswith("]") else host
        ipaddress.ip_address(candidate)
        is_dotted_quad_or_ipv6 = True
    except ValueError:
        pass

    if not is_dotted_quad_or_ipv6 and _looks_like_ip_literal(host):
        return False, f"refusing non-standard IP literal host ({host})"

    if not is_dotted_quad_or_ipv6:
        resolver = resolve_fn or _resolve_addresses
        try:
            addresses = resolver(host)
        except OSError:
            return False, f"could not resolve host ({host})"
        for addr in addresses:
            try:
                ip = ipaddress.ip_address(addr)
            except ValueError:
                continue
            if _is_private_ip(ip):
                return False, f"refusing to fetch host ({host}) that resolves to a private address ({addr})"

    return True, ""


def _resolve_addresses(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None)
    return sorted({info[4][0] for info in infos})


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
    """Return a refusal reason if this outbound research must be blocked, else None."""
    if url is not None:
        ok, reason = is_public_url(url, resolve_fn=resolve_fn)
        if not ok:
            return f"Blocked: {reason}."
    if query is not None:
        ok, reason = is_safe_query(query)
        if not ok:
            return f"Blocked: {reason}."
    return None


__all__ = ["is_public_url", "is_safe_query", "guard_outbound"]
