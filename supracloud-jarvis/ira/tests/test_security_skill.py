"""Security skill reasoning through the Hermes bridge (Option A).

Skips unless the gateway is reachable AND IRA_HERMES_KEY is set, so CI stays green
without a running gateway. The owner-gate / tools / DB live in agents/security.py
(IRA side) and are out of scope for this reasoning test.
"""
import os

import pytest

from hermes_bridge import HermesConfig
from skills.security import analyze_security, load_persona


def _gateway_available() -> bool:
    if not os.getenv("IRA_HERMES_KEY"):
        return False
    try:
        import httpx

        cfg = HermesConfig()
        r = httpx.get(
            cfg.base_url.rstrip("/") + "/models",
            headers={"Authorization": f"Bearer {cfg.api_key}"},
            timeout=5,
        )
        return r.status_code == 200
    except Exception:
        return False


def test_persona_loads_and_substitutes_owner():
    persona = load_persona("Praveen")
    assert "Security Guardian" in persona
    assert "Praveen" in persona and "{owner_name}" not in persona


@pytest.mark.skipif(
    not _gateway_available(),
    reason="Hermes gateway not reachable / IRA_HERMES_KEY unset",
)
def test_security_reasoning_via_bridge():
    events = [
        {
            "severity": "HIGH",
            "type": "ssh_bruteforce",
            "source_ip": "10.0.0.5",
            "description": "42 failed SSH logins in 60s",
            "time": "2026-06-03T08:00:00",
        }
    ]
    out = analyze_security("Assess the current threats.", events=events, owner_name="Praveen")
    assert isinstance(out, str) and out.strip(), "empty analysis"
    low = out.lower()
    assert (
        any(sev in out for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"])
        or "ssh" in low
        or "action" in low
    ), f"response not security-style: {out[:200]!r}"
