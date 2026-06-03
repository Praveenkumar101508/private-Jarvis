"""Integration smoke test for the Hermes bridge (IRA -> HTTP -> gateway).

Skips unless the gateway is reachable AND IRA_HERMES_KEY is set, so CI without a
running gateway stays green. Run locally with `hermes gateway` up and the env from
ira/config/hermes.env.example exported.
"""
import os

import pytest

from hermes_bridge import HermesBridge, HermesConfig


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
def test_bridge_ask_returns_text():
    reply = HermesBridge().ask("What is 2 + 2? Reply with only the number.")
    assert isinstance(reply, str) and reply.strip(), "bridge returned empty text"
    assert "4" in reply, f"unexpected reply: {reply!r}"
