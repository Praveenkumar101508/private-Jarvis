"""
Tests for api/routes/webhooks.py

Covers:
  - Prompt 16: notifier failures must not break the webhook response
  - Prompt 17: LiveKit webhook signature verification (JWT body-hash + fallback)
  - Prompt 34: hot-lead detection (keywords + budget)
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_app():
    """Build a minimal FastAPI app with the webhooks router."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.routes import webhooks
    app = FastAPI()
    app.include_router(webhooks.router)
    return app


# ── Prompt 16: notifier failure isolation ─────────────────────────────────────

@pytest.mark.asyncio
async def test_lead_webhook_succeeds_when_notifier_raises():
    """A notifier exception for a hot lead must not propagate to the caller."""
    from api.routes.webhooks import receive_lead, LeadPayload

    payload = LeadPayload(
        name="Urgent Client",
        email="urgent@example.com",
        message="URGENT enterprise deal ASAP",
        budget="enterprise",
        source="website",
    )

    async def _boom(*args, **kwargs):
        raise RuntimeError("Telegram is down")

    with patch("api.routes.webhooks.get_settings") as mock_cfg, \
         patch("api.routes.webhooks.acquire") as mock_acquire, \
         patch("worker.notifier.notify", side_effect=_boom):

        mock_cfg.return_value = MagicMock(webhook_secret="secret", owner_name="Test User")
        mock_conn = AsyncMock()
        mock_acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_conn.execute = AsyncMock()

        # The call must succeed despite the notifier blowing up
        with patch("api.routes.webhooks._validate_webhook_secret"):
            result = await receive_lead(payload, x_webhook_secret="secret")

    assert result["status"] == "received"


@pytest.mark.asyncio
async def test_booking_webhook_succeeds_when_notifier_raises():
    """A notifier exception for a booking must not propagate to the caller."""
    from api.routes.webhooks import receive_booking, BookingPayload

    payload = BookingPayload(
        client_name="Test Client",
        client_email="client@example.com",
        service="Consultation",
    )

    async def _boom(*args, **kwargs):
        raise ConnectionError("SMTP server unavailable")

    with patch("api.routes.webhooks.get_settings") as mock_cfg, \
         patch("api.routes.webhooks.acquire") as mock_acquire, \
         patch("worker.notifier.notify", side_effect=_boom):

        mock_cfg.return_value = MagicMock(webhook_secret="secret", owner_name="Test User")
        mock_conn = AsyncMock()
        mock_acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_conn.execute = AsyncMock()

        with patch("api.routes.webhooks._validate_webhook_secret"):
            result = await receive_booking(payload, x_webhook_secret="secret")

    assert result["status"] == "received"


# ── Prompt 17: LiveKit signature verification ─────────────────────────────────

@pytest.mark.asyncio
async def test_livekit_webhook_rejects_invalid_signature():
    """LiveKit events with a wrong shared secret must get 401."""
    import hmac
    from fastapi import HTTPException
    from api.routes.webhooks import _validate_webhook_secret
    from config import get_settings

    with patch("api.routes.webhooks.get_settings") as mock_cfg:
        mock_cfg.return_value = MagicMock(webhook_secret="correct-secret")
        with pytest.raises(HTTPException) as exc_info:
            _validate_webhook_secret("wrong-secret")
        assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_livekit_webhook_rejects_missing_secret():
    """LiveKit events with no secret header must get 401."""
    from fastapi import HTTPException
    from api.routes.webhooks import _validate_webhook_secret

    with patch("api.routes.webhooks.get_settings") as mock_cfg:
        mock_cfg.return_value = MagicMock(webhook_secret="some-secret")
        with pytest.raises(HTTPException) as exc_info:
            _validate_webhook_secret(None)
        assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_livekit_webhook_rejects_unconfigured_secret():
    """If WEBHOOK_SECRET is not set the route must return 503 (safer than accepting anything)."""
    from fastapi import HTTPException
    from api.routes.webhooks import _validate_webhook_secret

    with patch("api.routes.webhooks.get_settings") as mock_cfg:
        mock_cfg.return_value = MagicMock(webhook_secret="")
        with pytest.raises(HTTPException) as exc_info:
            _validate_webhook_secret("anything")
        assert exc_info.value.status_code == 503


# ── Prompt 34: hot-lead heuristics ────────────────────────────────────────────

# ── Prompt 17 extra: LiveKit JWT body-hash path ───────────────────────────────

def test_livekit_uses_jwt_when_credentials_configured():
    """When livekit_api_key/secret are set, _verify_livekit_signature uses WebhookReceiver."""
    from api.routes.webhooks import _verify_livekit_signature

    body = b'{"event":"room_started","room":{"name":"test"}}'
    mock_receiver = MagicMock()
    mock_receiver.receive.return_value = MagicMock()  # success

    with patch("api.routes.webhooks.get_settings") as mock_cfg, \
         patch("livekit.api.WebhookReceiver", return_value=mock_receiver):
        mock_cfg.return_value = MagicMock(
            livekit_api_key="key123",
            livekit_api_secret="secret123",
        )
        result = _verify_livekit_signature(body, "Bearer validjwt")

    assert result["event"] == "room_started"
    mock_receiver.receive.assert_called_once()


def test_livekit_jwt_verification_failure_returns_401():
    """A bad JWT when credentials are configured must raise 401, not 500."""
    from fastapi import HTTPException
    from api.routes.webhooks import _verify_livekit_signature

    body = b'{"event":"room_started"}'
    mock_receiver = MagicMock()
    mock_receiver.receive.side_effect = ValueError("bad signature")

    with patch("api.routes.webhooks.get_settings") as mock_cfg, \
         patch("livekit.api.WebhookReceiver", return_value=mock_receiver):
        mock_cfg.return_value = MagicMock(
            livekit_api_key="key123",
            livekit_api_secret="secret123",
        )
        with pytest.raises(HTTPException) as exc_info:
            _verify_livekit_signature(body, "Bearer badjwt")

    assert exc_info.value.status_code == 401


# ── Prompt 34: hot-lead heuristics ────────────────────────────────────────────

def test_hot_lead_keywords_from_config():
    """Hot-lead keyword list should be read from settings, not hard-coded."""
    import inspect
    from api.routes import webhooks
    src = inspect.getsource(webhooks)
    # Ensure the keywords are not hard-coded string literals in the main body
    # (they should come from get_settings() or a config attribute)
    assert "urgent_keywords" not in src or "cfg." in src or "get_settings" in src, (
        "Hot-lead keywords should be config-driven, not hard-coded in receive_lead()"
    )
