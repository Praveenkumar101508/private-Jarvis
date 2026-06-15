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
from typing import Optional
from urllib.parse import urlparse

_PRIVATE_HOST_SUFFIXES = (".local", ".internal", ".lan", ".localdomain")

# Markers that suggest a secret/credential is being smuggled into an outbound query.
_SECRET_RE = re.compile(
    r"(BEGIN [A-Z ]*PRIVATE KEY|api[_-]?key\s*[:=]|password\s*[:=]|passwd\s*[:=]"
    r"|secret\s*[:=]|aws_secret|bearer\s+[A-Za-z0-9._\-]{20,})",
    re.IGNORECASE,
)
# Local filesystem paths / file scheme that should never be sent to a web backend.
_LOCAL_PATH_RE = re.compile(r"(^|\s)(/etc/|/var/|/root/|/home/|[A-Za-z]:\\|file://)")


def _is_private_host(host: str) -> bool:
    host = (host or "").lower()
    if host == "localhost" or host.endswith(_PRIVATE_HOST_SUFFIXES):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified
    except ValueError:
        return False  # an ordinary public domain name


def is_public_url(url: str) -> tuple[bool, str]:
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https"):
        return False, f"only http(s) URLs may be fetched (got scheme {parsed.scheme or 'none'!r})"
    host = parsed.hostname or ""
    if not host:
        return False, "URL has no host"
    if _is_private_host(host):
        return False, f"refusing to fetch a private/internal host ({host})"
    return True, ""


def is_safe_query(text: str) -> tuple[bool, str]:
    if _SECRET_RE.search(text or ""):
        return False, "query appears to contain a secret/credential — not sent outbound"
    if _LOCAL_PATH_RE.search(text or ""):
        return False, "query appears to contain a local file path — not sent outbound"
    return True, ""


def guard_outbound(*, url: Optional[str] = None, query: Optional[str] = None) -> Optional[str]:
    """Return a refusal reason if this outbound research must be blocked, else None."""
    if url is not None:
        ok, reason = is_public_url(url)
        if not ok:
            return f"Blocked: {reason}."
    if query is not None:
        ok, reason = is_safe_query(query)
        if not ok:
            return f"Blocked: {reason}."
    return None


__all__ = ["is_public_url", "is_safe_query", "guard_outbound"]
