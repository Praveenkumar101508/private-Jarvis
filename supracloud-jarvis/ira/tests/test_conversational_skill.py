"""Conversational (core personality) skill — persona load + bridge smoke.

History is delegated to the gateway session (session_key); not tested here.
"""
import os

import pytest

from cortex_bridge import CortexConfig
from skills._common import load_persona
from skills.conversational import converse


def test_conversational_persona_loads():
    persona = load_persona("conversational", owner_name="Praveen")
    assert "IRA" in persona and "Maximally Helpful" in persona
    assert "Praveen" in persona and "{owner_name}" not in persona


def _gateway_available() -> bool:
    if not os.getenv("IRA_CORTEX_KEY"):
        return False
    try:
        import httpx

        cfg = CortexConfig()
        r = httpx.get(
            cfg.base_url.rstrip("/") + "/models",
            headers={"Authorization": f"Bearer {cfg.api_key}"},
            timeout=5,
        )
        return r.status_code == 200
    except Exception:
        return False


@pytest.mark.skipif(
    not _gateway_available(),
    reason="Cortex gateway not reachable / IRA_CORTEX_KEY unset",
)
def test_conversational_via_bridge():
    out = converse("In one short sentence, say hello.", owner_name="Praveen")
    assert isinstance(out, str) and len(out.strip()) > 5, f"weak reply: {out!r}"
