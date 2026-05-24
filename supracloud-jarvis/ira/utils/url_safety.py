"""
Shared URL safety utility — SSRF protection for all browser/HTTP calls.

is_safe_url(url) returns True only for publicly-routable HTTP/HTTPS URLs.
Blocks:
  - Non-HTTP/HTTPS schemes
  - Private/RFC-1918 IP ranges
  - Loopback (127.x, ::1)
  - Link-local (169.254.x — AWS/GCP metadata endpoint)
  - Unique-local IPv6 (fc00::/7)
  - Known internal hostnames (.local, .internal, .corp, localhost)
"""

from __future__ import annotations

import ipaddress
import logging
import re
from urllib.parse import urlparse

logger = logging.getLogger("ira.url_safety")

_BLOCKED_HOSTS = re.compile(
    r"^(localhost|.*\.local|.*\.internal|.*\.corp)$", re.I
)

# CIDR ranges that must never be reached
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),      # Loopback
    ipaddress.ip_network("10.0.0.0/8"),        # RFC-1918 private
    ipaddress.ip_network("172.16.0.0/12"),     # RFC-1918 private
    ipaddress.ip_network("192.168.0.0/16"),    # RFC-1918 private
    ipaddress.ip_network("169.254.0.0/16"),    # Link-local / AWS metadata
    ipaddress.ip_network("::1/128"),           # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),          # IPv6 unique-local
    ipaddress.ip_network("fe80::/10"),         # IPv6 link-local
]


def is_safe_url(url: str) -> bool:
    """Return True only for publicly routable HTTP/HTTPS URLs."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            logger.warning(f"URL blocked — non-HTTP scheme: {url!r}")
            return False
        host = parsed.hostname or ""
        if not host:
            return False
        if _BLOCKED_HOSTS.match(host):
            logger.warning(f"URL blocked — internal hostname: {url!r}")
            return False
        # Try to parse as IP address
        try:
            addr = ipaddress.ip_address(host)
            for network in _BLOCKED_NETWORKS:
                if addr in network:
                    logger.warning(f"URL blocked — private/reserved IP {addr} in {network}: {url!r}")
                    return False
        except ValueError:
            pass  # It's a hostname — already checked above
        return True
    except Exception as exc:
        logger.warning(f"URL safety check failed for {url!r}: {exc}")
        return False
