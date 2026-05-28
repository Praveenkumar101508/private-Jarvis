"""
TOTP two-factor authentication endpoints.  # Feat P26

POST /auth/totp/enroll  — generate and persist a TOTP secret; returns provisioning URI
POST /auth/totp/verify  — validate a TOTP code against the stored secret

The login endpoint (main.py) checks totp_secrets on every successful password
auth — if an enrolled secret exists the caller must also supply a valid totp_code
form field, or the token is refused.
"""
from __future__ import annotations

import pyotp
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.middleware.auth import require_auth
from utils.db import acquire

router = APIRouter(prefix="/auth/totp", tags=["auth"])


class EnrollResponse(BaseModel):
    provisioning_uri: str
    secret: str  # returned once so the user can save it before scanning QR


class VerifyRequest(BaseModel):
    code: str


@router.post("/enroll", response_model=EnrollResponse, status_code=201)
async def totp_enroll(_user: str = Depends(require_auth)):
    """Generate and store a fresh TOTP secret; re-enrolling replaces the old one."""
    secret = pyotp.random_base32()
    async with acquire() as conn:
        await conn.execute(
            """INSERT INTO totp_secrets (username, secret)
               VALUES ($1, $2)
               ON CONFLICT (username) DO UPDATE SET secret=$2, enrolled_at=NOW()""",
            _user, secret,
        )
    uri = pyotp.TOTP(secret).provisioning_uri(name=_user, issuer_name="SupraCloud IRA")
    return EnrollResponse(provisioning_uri=uri, secret=secret)


@router.post("/verify")
async def totp_verify(body: VerifyRequest, _user: str = Depends(require_auth)):
    """Confirm the user's authenticator app is producing valid codes."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT secret FROM totp_secrets WHERE username=$1", _user
        )
    if not row:
        raise HTTPException(status_code=400, detail="TOTP not enrolled — call /auth/totp/enroll first")
    if not pyotp.TOTP(row["secret"]).verify(body.code, valid_window=1):
        raise HTTPException(status_code=401, detail="Invalid or expired TOTP code")
    return {"verified": True}
