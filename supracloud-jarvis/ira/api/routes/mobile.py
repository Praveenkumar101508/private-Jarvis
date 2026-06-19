"""api/routes/mobile.py — mobile-app support endpoints (#3).

The IRA mobile app reaches the box over a private Tailscale mesh and authenticates
with the existing JWT. These endpoints let it register for push and verify
connectivity:

  POST   /mobile/devices   — register this phone's Expo push token (owner-gated)
  DELETE /mobile/devices   — unregister a token
  GET    /mobile/devices   — how many devices are registered (count only; no token leak)
  GET    /mobile/ping      — connectivity/identity check for the app over Tailscale

Push delivery + the device registry live in worker.push_mobile and ride the
existing worker.notifier channel. Heavier deps are imported lazily so this module
stays light. All routes are owner-gated via the existing auth dependency.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.middleware.auth import require_auth

router = APIRouter(prefix="/mobile", tags=["mobile"])
logger = logging.getLogger("ira.mobile")


class DeviceRegistration(BaseModel):
    token: str
    platform: str | None = None   # "ios" | "android" (advisory)


@router.post("/devices")
async def register_device(reg: DeviceRegistration, _user: str = Depends(require_auth)):
    from worker import push_mobile

    if not push_mobile.is_valid_token(reg.token):
        raise HTTPException(status_code=422, detail="Invalid Expo push token.")
    await push_mobile.register_device(reg.token, platform=reg.platform)
    return {"status": "registered"}


@router.delete("/devices")
async def unregister_device(reg: DeviceRegistration, _user: str = Depends(require_auth)):
    from worker import push_mobile

    await push_mobile.unregister_device(reg.token)
    return {"status": "unregistered"}


@router.get("/devices")
async def list_devices(_user: str = Depends(require_auth)):
    from worker import push_mobile

    tokens = await push_mobile.list_devices()
    return {"count": len(tokens)}   # count only — never leak the tokens themselves


@router.get("/ping")
async def ping(_user: str = Depends(require_auth)):
    """Lightweight identity/connectivity check for the app (over Tailscale)."""
    from config import get_settings

    return {"ok": True, "service": "ira", "version": get_settings().ira_version}
