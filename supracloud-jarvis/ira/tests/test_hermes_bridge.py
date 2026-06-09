"""Integration smoke test for the Hermes bridge (IRA -> HTTP -> gateway).

Skips unless the gateway is reachable AND IRA_HERMES_KEY is set, so CI without a
running gateway stays green. Run locally with `hermes gateway` up and the env from
ira/config/hermes.env.example exported.
"""
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

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


# ── Unit tests for the session-header contract (no live gateway needed) ───────

def _bridge_with_mock():
    """A HermesBridge whose HTTP client is mocked, plus the create() mock."""
    bridge = HermesBridge(HermesConfig(api_key="test-key"))
    fake = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
    )
    bridge._client = MagicMock()
    bridge._client.chat.completions.create.return_value = fake
    return bridge, bridge._client.chat.completions.create


def test_ask_sends_both_session_headers_and_system_message():
    bridge, create = _bridge_with_mock()
    bridge.ask("hello", system="persona", session_id="conv-1", user_key="owner-1")
    kwargs = create.call_args.kwargs
    headers = kwargs["extra_headers"]
    assert headers["X-Hermes-Session-Id"] == "conv-1"   # thread continuity
    assert headers["X-Hermes-Session-Key"] == "owner-1"  # stable memory scope
    messages = kwargs["messages"]
    assert messages[0] == {"role": "system", "content": "persona"}
    assert messages[-1] == {"role": "user", "content": "hello"}


def test_ask_bare_call_is_unchanged():
    bridge, create = _bridge_with_mock()
    bridge.ask("hi")
    kwargs = create.call_args.kwargs
    assert "extra_headers" not in kwargs
    assert kwargs["messages"] == [{"role": "user", "content": "hi"}]


def test_ask_session_key_is_deprecated_alias_for_memory_scope():
    bridge, create = _bridge_with_mock()
    bridge.ask("hi", session_key="legacy-scope")
    headers = create.call_args.kwargs["extra_headers"]
    assert headers["X-Hermes-Session-Key"] == "legacy-scope"
    assert "X-Hermes-Session-Id" not in headers


def test_ask_user_key_wins_over_session_key():
    bridge, create = _bridge_with_mock()
    bridge.ask("hi", user_key="new", session_key="old")
    assert create.call_args.kwargs["extra_headers"]["X-Hermes-Session-Key"] == "new"
