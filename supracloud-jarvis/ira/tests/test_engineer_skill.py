"""Engineer Mode skill — persona load + bridge smoke."""
import os

import pytest

from cortex_bridge import CortexConfig
from skills._common import load_persona
from skills.engineer import engineer


def test_engineer_persona_loads():
    persona = load_persona("engineer")
    assert "Engineer Mode" in persona and "Step 3" in persona


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
def test_engineer_via_bridge():
    out = engineer("Add a /health endpoint to a FastAPI app.")
    assert isinstance(out, str) and out.strip(), "empty engineer reply"
    low = out.lower()
    assert "step" in low or "diff" in low or "plan" in low or len(out) > 40
