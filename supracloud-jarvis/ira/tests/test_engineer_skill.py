"""Engineer Mode skill — persona load + bridge smoke."""
import os

import pytest

from hermes_bridge import HermesConfig
from skills._common import load_persona
from skills.engineer import engineer


def test_engineer_persona_loads():
    persona = load_persona("engineer")
    assert "Engineer Mode" in persona and "Step 3" in persona


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
def test_engineer_via_bridge():
    out = engineer("Add a /health endpoint to a FastAPI app.")
    assert isinstance(out, str) and out.strip(), "empty engineer reply"
    low = out.lower()
    assert "step" in low or "diff" in low or "plan" in low or len(out) > 40
