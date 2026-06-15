"""Expert-Mode deliberation through the bridge (ira/subagents).

The bridge smoke runs 5 sequential gateway calls (4 specialists + supervisor), so it's
slower; skipped unless the gateway is reachable.
"""
import os

import pytest

from cortex_bridge import CortexBridge, CortexConfig
from subagents import deliberate


def test_specialist_roles_defined():
    from subagents import _specialists, _supervisor

    roles = _specialists("Praveen")
    assert len(roles) == 4
    labels = " ".join(label for label, _ in roles)
    assert "Researcher" in labels and "Critic" in labels and "Executor" in labels and "Creator" in labels
    assert "Supervisor" in _supervisor("Praveen")


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
def test_deliberate_via_bridge():
    out = CortexBridge().deliberate("How should a small web app store user secrets?")
    assert isinstance(out, str) and out.strip()
    # The wrapper structure proves the orchestration ran (4 specialists + supervisor).
    assert "Supervisor Synthesis" in out
    assert "Expert Mode — Collaborative Analysis" in out
    assert len(out) > 200
