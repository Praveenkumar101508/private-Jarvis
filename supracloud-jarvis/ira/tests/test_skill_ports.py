"""Persona-load tests for the batch-ported skills + one bridge smoke (researcher).

The IRA-side pieces (owner-gate, tools, DB) stay in agents/*.py and are out of scope
here. The bridge path itself is identical for every skill (skills._common.run_skill),
already exercised by the security/tutor tests, so one bridge smoke covers the batch.
"""
import os

import pytest

from hermes_bridge import HermesConfig
from skills._common import load_persona

PORTED = [
    ("researcher", "Researcher"),
    ("career", "Career"),
    ("creator", "Meta Skill Creator"),
    ("website", "Business Manager"),
    ("digital", "Digital"),
    ("executor", "Executor"),
]


@pytest.mark.parametrize("name,marker", PORTED)
def test_persona_loads(name, marker):
    persona = load_persona(name)
    assert persona.strip(), f"{name}: empty persona"
    assert marker in persona, f"{name}: missing marker {marker!r}"


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
def test_researcher_via_bridge():
    from skills.researcher import research

    out = research("In one sentence, what is a race condition?")
    assert isinstance(out, str) and out.strip(), "empty research reply"
    assert "race" in out.lower() or "condition" in out.lower() or len(out) > 20
