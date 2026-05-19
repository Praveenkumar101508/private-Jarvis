"""
Voice endpoints.

GET  /voice/token          → generate a LiveKit access token for the frontend
POST /voice/enroll         → owner submits reference audio for biometric enrolment
GET  /voice/profile/status → check whether an owner voice profile exists
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from api.middleware.auth import require_auth
from config import get_settings

router = APIRouter(prefix="/voice", tags=["voice"])
logger = logging.getLogger("ira.voice.api")


# ── Response models ───────────────────────────────────────────────────────────

class LiveKitTokenResponse(BaseModel):
    token: str
    room: str
    livekit_url: str


class EnrolmentResponse(BaseModel):
    status: str
    segments_processed: int
    message: str


# ── LiveKit access token factory ──────────────────────────────────────────────

@router.get("/token", response_model=LiveKitTokenResponse)
async def get_livekit_token(_user: str = Depends(require_auth)):
    """
    Generate a signed LiveKit access token for the authenticated user.

    The token grants room-join access to the IRA voice room and is valid
    for 1 hour. The frontend VoiceButton uses this token to connect to
    LiveKit and start a voice session with IRA.
    """
    cfg = get_settings()

    if not cfg.livekit_api_key or not cfg.livekit_api_secret:
        raise HTTPException(
            status_code=503,
            detail="LiveKit is not configured. Set LIVEKIT_API_KEY and LIVEKIT_API_SECRET in .env",
        )

    try:
        from livekit.api import AccessToken, VideoGrants

        token = (
            AccessToken(cfg.livekit_api_key, cfg.livekit_api_secret)
            .with_identity(_user)
            .with_name(_user)
            .with_grants(
                VideoGrants(
                    room_join=True,
                    room=cfg.livekit_room_name,
                    can_publish=True,      # user can send microphone audio
                    can_subscribe=True,    # user can hear IRA's TTS audio
                )
            )
        )
        jwt = token.to_jwt()
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="livekit-api package not installed. Run: pip install livekit-api",
        )
    except Exception as e:
        logger.error(f"LiveKit token generation failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate voice token")

    return LiveKitTokenResponse(
        token=jwt,
        room=cfg.livekit_room_name,
        livekit_url=f"wss://{cfg.ira_domain}",
    )


# ── Biometric voice enrolment ─────────────────────────────────────────────────

@router.post("/enroll", response_model=EnrolmentResponse)
async def enroll_voice(
    audio_files: list[UploadFile] = File(
        ...,
        description="3–10 WAV/PCM audio files (16kHz mono) of the owner speaking.",
    ),
    _user: str = Depends(require_auth),
):
    """
    Owner voice enrolment endpoint.

    Submit 3–10 audio segments (≥3 seconds each, 16kHz mono PCM/WAV).
    IRA computes an ECAPA-TDNN embedding for each segment, averages them
    into a robust reference profile, and stores it in the database.

    Security: only the admin user can enrol. The stored profile is used for
    all subsequent biometric gate checks on voice requests.

    Recommended: record yourself saying different sentences of varying length
    to build a representative voice profile.
    """
    cfg = get_settings()
    if _user != cfg.ira_admin_username:
        raise HTTPException(
            status_code=403,
            detail="Only the system administrator may enrol a voice profile.",
        )

    if len(audio_files) < 1:
        raise HTTPException(status_code=400, detail="At least 1 audio file is required.")
    if len(audio_files) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 audio files per enrolment.")

    try:
        from voice.biometrics import compute_embedding, save_owner_profile, invalidate_profile_cache
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Biometric module unavailable. Ensure speechbrain is installed.",
        )

    embeddings = []
    failed = 0

    for f in audio_files:
        audio_bytes = await f.read()
        # Strip WAV header if present (look for 'RIFF' magic bytes)
        if audio_bytes[:4] == b"RIFF":
            # Skip 44-byte WAV header to get to PCM data
            audio_bytes = audio_bytes[44:]

        embedding = await compute_embedding(audio_bytes)
        if embedding is not None:
            embeddings.append(embedding)
        else:
            failed += 1
            logger.warning(f"Embedding failed for file: {f.filename}")

    if not embeddings:
        raise HTTPException(
            status_code=422,
            detail=f"Could not extract embeddings from any of the {len(audio_files)} files. "
                   f"Ensure audio is 16kHz mono PCM/WAV, ≥3 seconds.",
        )

    success = await save_owner_profile(embeddings)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save voice profile to database.")

    invalidate_profile_cache()

    return EnrolmentResponse(
        status="enrolled",
        segments_processed=len(embeddings),
        message=(
            f"Voice profile enrolled successfully from {len(embeddings)} segment(s). "
            f"{'(' + str(failed) + ' segment(s) skipped due to processing errors.) ' if failed else ''}"
            f"Biometric gate is now active for voice requests."
        ),
    )


@router.get("/profile/status")
async def profile_status(_user: str = Depends(require_auth)):
    """Check whether an owner voice profile has been enrolled."""
    try:
        from utils.db import acquire
        async with acquire() as conn:
            row = await conn.fetchrow(
                "SELECT owner_name, created_at, updated_at FROM voice_profiles LIMIT 1"
            )
        if row:
            return {
                "enrolled": True,
                "owner": row["owner_name"],
                "enrolled_at": row["created_at"].isoformat(),
                "last_updated": row["updated_at"].isoformat(),
            }
        return {"enrolled": False, "message": "No voice profile found. POST /voice/enroll to register."}
    except Exception as e:
        return {"enrolled": False, "error": str(e)}
