"""
Phase 3: Voice router — LiveKit token generation and voice session management
"""
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from livekit import api

from config import settings

router = APIRouter()


class TokenRequest(BaseModel):
    room_name: str
    participant_name: str = "user"
    identity: str | None = None


class VoiceSession(BaseModel):
    room_name: str
    token: str
    livekit_url: str
    tts_provider: str
    stt_provider: str


@router.post("/token", response_model=VoiceSession)
async def create_voice_token(req: TokenRequest):
    """Generate a LiveKit token for a voice session with IRA."""
    try:
        token = api.AccessToken(
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
        )
        token.with_identity(req.identity or req.participant_name)
        token.with_name(req.participant_name)
        token.with_grants(
            api.VideoGrants(
                room_join=True,
                room=req.room_name,
                can_publish=True,
                can_subscribe=True,
            )
        )
        jwt = token.to_jwt()

        return VoiceSession(
            room_name=req.room_name,
            token=jwt,
            livekit_url=settings.livekit_url,
            tts_provider=settings.tts_provider,
            stt_provider=settings.stt_provider,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/providers")
async def get_voice_providers():
    return {
        "stt": settings.stt_provider,
        "tts": settings.tts_provider,
        "voice_id": settings.elevenlabs_voice_id if settings.tts_provider == "elevenlabs" else None,
        "azure_voice": settings.azure_tts_voice if settings.tts_provider == "azure" else None,
    }
