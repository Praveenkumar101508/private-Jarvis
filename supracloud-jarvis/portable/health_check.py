#!/usr/bin/env python3
"""
portable/health_check.py — readiness gate for the IRA portable launcher.

Polls the REAL health endpoints the app exposes (api/routes/health.py):
  * GET /health         → overall status: "ok" | "degraded" | "down" + per-service
  * GET /health/detail  → independent per-pillar status

(The launcher spec mentioned /health/{live,ready,dependencies}; those paths do not
exist in this codebase, so we poll the actual /health + /health/detail instead.)

Exit 0 only when /health reports "ok". On "degraded"/"down"/unreachable it prints a
human-readable breakdown of which dependency is failing and exits non-zero — never
silently. Pure standard library (urllib): no extra dependency to install on a USB.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Callable, Optional

DEFAULT_BASE = "http://127.0.0.1:8000"


def _http_get_json(url: str, timeout: float) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - localhost only
        return json.loads(resp.read().decode("utf-8"))


def evaluate_health(payload: dict) -> tuple[bool, str]:
    """Interpret a /health payload → (ready, human message). Pure: unit-testable."""
    status = (payload or {}).get("status", "down")
    services = (payload or {}).get("services") or payload.get("dependencies") or {}
    if status == "ok":
        return True, "all systems ok"

    broken = []
    for name, val in services.items() if isinstance(services, dict) else []:
        st = val.get("status") if isinstance(val, dict) else val
        if st != "ok":
            broken.append(f"{name}={st}")
    detail = ("; ".join(broken)) if broken else "no per-service detail"
    return False, f"status={status} ({detail})"


def check_once(
    base_url: str = DEFAULT_BASE,
    *,
    timeout: float = 3.0,
    fetch: Optional[Callable[[str, float], dict]] = None,
) -> tuple[bool, str]:
    """One health probe. ``fetch`` is injectable for tests."""
    get = fetch or _http_get_json
    try:
        payload = get(f"{base_url}/health", timeout)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return False, f"unreachable at {base_url}/health ({exc})"
    return evaluate_health(payload)


def wait_for_ready(
    base_url: str = DEFAULT_BASE,
    *,
    total_timeout: float = 90.0,
    interval: float = 2.0,
    timeout: float = 3.0,
    fetch: Optional[Callable[[str, float], dict]] = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> tuple[bool, str]:
    """Poll until ready or the budget runs out. Returns (ready, last message)."""
    deadline = now() + total_timeout
    ready, msg = False, "not started"
    while now() < deadline:
        ready, msg = check_once(base_url, timeout=timeout, fetch=fetch)
        if ready:
            return True, msg
        sleep(interval)
    return ready, msg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Wait for IRA to be healthy.")
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--timeout", type=float, default=90.0, help="total wait budget (s)")
    parser.add_argument("--once", action="store_true", help="probe once and exit")
    args = parser.parse_args(argv)

    if args.once:
        ready, msg = check_once(args.base_url)
    else:
        ready, msg = wait_for_ready(args.base_url, total_timeout=args.timeout)

    if ready:
        print(f"IRA is healthy: {msg}")
        return 0
    print(f"IRA is NOT healthy: {msg}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
