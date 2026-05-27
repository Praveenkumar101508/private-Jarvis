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
  - Fix L14: hostnames that resolve to a private/reserved IP address (DNS rebinding)
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
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
    """Return True only for publicly routable HTTP/HTTPS URLs.

    Fix L14: now resolves hostnames to their IP address before approving the
    request — mirrors the DNS-rebinding protection added to browser_tools._is_safe_url()
    in Fix #39.  A DNS rebinding attack can make a safe-looking hostname resolve
    to an internal IP at connection time; checking the resolved IP here closes
    that window for computer_use.py and any other caller of this shared utility.
    """
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

        # Resolve to IP — handles both literals and hostnames
        try:
            addr = ipaddress.ip_address(host)
        except ValueError:
            # Hostname: resolve synchronously and check the returned IP (Fix L14)
            try:
                resolved = socket.gethostbyname(host)
                addr = ipaddress.ip_address(resolved)
            except (socket.gaierror, ValueError):
                logger.warning(f"URL blocked — hostname unresolvable: {url!r}")
                return False  # Unresolvable → deny

        for network in _BLOCKED_NETWORKS:
            if addr in network:
                logger.warning(f"URL blocked — private/reserved IP {addr} in {network}: {url!r}")
                return False

        return True
    except Exception as exc:
        logger.warning(f"URL safety check failed for {url!r}: {exc}")
        return False
