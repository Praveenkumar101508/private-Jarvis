"""Architect: Evolution-Team debate roles + code-gen skill.

Unit tests are offline. The implement() bridge smoke (1 call) runs when the gateway is
up; the full 5-call proposal debate reuses the proven subagents.deliberate pattern and is
verified manually rather than in the suite (to keep it fast).
"""
import os

import pytest

from hermes_bridge import HermesConfig
from skills._common import load_persona
from skills.architect import implement


def test_capability_map_and_roles():
    from subagents.architect import IRA_CAPABILITY_MAP, _researcher, _supervisor

    assert IRA_CAPABILITY_MAP["implemented"] and IRA_CAPABILITY_MAP["missing"]
    assert "RESEARCHER" in _researcher("Praveen")
    assert "approval" in _supervisor("Praveen").lower()


def test_codegen_persona_loads():
    persona = load_persona("architect")
    assert "Auto-Implementation" in persona and "diff" in persona.lower()
    assert "never" in persona.lower()  # the "diffs are never applied here" guardrail note


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


@pytest.mark.skipif(
    not _gateway_available(),
    reason="Hermes gateway not reachable / IRA_HERMES_KEY unset",
)
def test_implement_codegen_via_bridge():
    out = implement("Add a /health endpoint to the FastAPI app", proposal_context="Simple liveness probe.")
    assert isinstance(out, str) and out.strip()
    low = out.lower()
    assert any(t in low for t in ["diff", "implementation", "summary", "```", "def ", "health"]), out[:200]
