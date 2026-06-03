"""Tutor skill reasoning through the Hermes bridge (Option A).

Skips the bridge test unless the gateway is reachable AND IRA_HERMES_KEY is set.
IRA-side submission-evaluation (utils.tutor_tools) + memory are out of scope here.
"""
import os

import pytest

from hermes_bridge import HermesConfig
from skills._common import load_persona
from skills.tutor import tutor


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


def test_tutor_persona_loads():
    persona = load_persona("tutor")
    assert "Socratic" in persona and "Supracloud" in persona


@pytest.mark.skipif(
    not _gateway_available(),
    reason="Hermes gateway not reachable / IRA_HERMES_KEY unset",
)
def test_tutor_socratic_via_bridge():
    out = tutor("Teach me what a hash map is.")
    assert isinstance(out, str) and out.strip(), "empty tutor reply"
    assert "?" in out, f"expected a Socratic question, got: {out[:200]!r}"
