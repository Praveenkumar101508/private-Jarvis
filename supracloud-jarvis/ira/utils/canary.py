"""P5.2 — Canary tokens and honeypot tripwires.

Three complementary tripwires that fire a CRITICAL security_event on any access:

1. Honeypot HTTP paths (canary_router): attacker-probe URLs that legitimate
   clients never request (/.env, /admin, /wp-admin, etc.). Requests to these
   paths are logged as CRITICAL intrusion probes and receive a plain 404.

2. Canary JWT token (check_canary_token): a bearer-token value stored as
   IRA_CANARY_TOKEN. Any API request presenting this exact token fires CRITICAL
   before normal auth runs, indicating a stolen or replayed credential.

3. Ghost username (check_canary_username): a fake account name stored as
   IRA_CANARY_USERNAME. Any login attempt for this username fires CRITICAL,
   indicating an attacker probing credentials or operating from a stolen list.

All tripwires are:
  - Fail-silent: if IRA_CANARY_TOKEN / IRA_CANARY_USERNAME are not set the
    corresponding check is a no-op — safe in environments without the config.
  - Fail-soft on emission error: the CRITICAL event write failing never blocks
    the response path; the attacker still gets their 401/404.
  - Async-safe: all emit calls use asyncio.create_task() where a loop is running.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("ira.canary")

# ── Honeypot path list ────────────────────────────────────────────────────────

_CANARY_PATHS: list[str] = [
    "/.env",
    "/.env.local",
    "/.env.production",
    "/.env.backup",
    "/.git/config",
    "/.git/HEAD",
    "/admin",
    "/admin/login",
    "/wp-admin",
    "/wp-login.php",
    "/phpmyadmin",
    "/pma",
    "/actuator",
    "/actuator/health",
    "/actuator/env",
    "/console",
    "/_debug",
    "/config.php",
    "/server-status",
    "/server-info",
    "/xmlrpc.php",
    "/cgi-bin/",
    "/shell",
    "/cmd",
]

canary_router = APIRouter(tags=["_canary"])


async def _handle_canary_probe(request: Request, matched_path: str) -> JSONResponse:
    """Emit CRITICAL event and return 404 for any honeypot path access."""
    source_ip = request.client.host if request.client else None
    description = (
        f"Canary tripwire hit: {request.method} {matched_path} "
        f"from {source_ip} (UA: {request.headers.get('user-agent', '')[:80]})"
    )
    logger.warning("CANARY TRIGGERED: %s", description)
    try:
        from utils.security_events import emit_event
        asyncio.create_task(
            emit_event(
                "canary_tripwire_hit",
                "critical",
                source_ip=source_ip,
                description=description,
            )
        )
    except Exception as exc:
        logger.warning("canary: emit_event failed: %s", exc)
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


# Register each canary path for GET and POST (most scanners use both).
# The lambda captures `path` by value via default argument.
for _path in _CANARY_PATHS:
    async def _handler(request: Request, _p: str = _path) -> JSONResponse:
        return await _handle_canary_probe(request, _p)
    canary_router.add_api_route(
        _path,
        _handler,
        methods=["GET", "POST", "HEAD", "OPTIONS"],
        include_in_schema=False,
    )


# ── Canary JWT token ──────────────────────────────────────────────────────────

def get_canary_token() -> Optional[str]:
    """Return the configured canary bearer token value, or None if not set."""
    return os.environ.get("IRA_CANARY_TOKEN", "").strip() or None


async def check_canary_token(bearer_token: str, source_ip: Optional[str] = None) -> bool:
    """Return True and fire CRITICAL if bearer_token matches the canary token.

    Call this BEFORE normal JWT decode. If it returns True, refuse the request
    and do not proceed — the token is a known tripwire credential.
    """
    canary = get_canary_token()
    if not canary:
        return False
    if bearer_token.strip() == canary:
        description = (
            f"Canary JWT token used from {source_ip or 'unknown'} — "
            "stolen or replayed credential detected."
        )
        logger.critical("CANARY TOKEN USED: %s", description)
        try:
            from utils.security_events import emit_event
            await emit_event(
                "canary_token_used",
                "critical",
                source_ip=source_ip,
                description=description,
            )
        except Exception as exc:
            logger.warning("canary: emit_event failed: %s", exc)
        return True
    return False


# ── Ghost username ────────────────────────────────────────────────────────────

def get_canary_username() -> Optional[str]:
    """Return the configured ghost/canary username, or None if not set."""
    return os.environ.get("IRA_CANARY_USERNAME", "").strip() or None


async def check_canary_username(username: str, source_ip: Optional[str] = None) -> bool:
    """Return True and fire CRITICAL if the login username is the ghost account.

    Call this at the top of the login handler, before any password check or
    timing-equalisation sleep — but still return a realistic 401 to the caller.
    """
    canary = get_canary_username()
    if not canary:
        return False
    if username.lower() == canary.lower():
        description = (
            f"Ghost username '{canary}' login attempted from {source_ip or 'unknown'} — "
            "credential list leak or targeted attack."
        )
        logger.critical("GHOST USERNAME LOGIN: %s", description)
        try:
            from utils.security_events import emit_event
            await emit_event(
                "canary_username_login_attempt",
                "critical",
                source_ip=source_ip,
                description=description,
            )
        except Exception as exc:
            logger.warning("canary: emit_event failed: %s", exc)
        return True
    return False


__all__ = [
    "canary_router",
    "check_canary_token",
    "check_canary_username",
    "get_canary_token",
    "get_canary_username",
    "_CANARY_PATHS",
]
