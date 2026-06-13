"""
Voice endpoints.

GET  /voice/token          → generate a LiveKit access token for the frontend
POST /voice/enroll         → owner submits reference audio for biometric enrolment
GET  /voice/profile/status → check whether an owner voice profile exists
"""

from __future__ import annotations

import logging
import os
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from api.middleware.auth import require_auth
from config import get_settings

router = APIRouter(prefix="/voice", tags=["voice"])
logger = logging.getLogger("ira.voice.api")

# Anti-replay challenge TTL — challenges expire after 60 seconds.
# If the user hasn't spoken the phrase and submitted within 60 s the
# challenge is stale; the client must request a fresh one.
_CHALLENGE_TTL = 60  # seconds


# ── Response models ───────────────────────────────────────────────────────────

class LiveKitTokenResponse(BaseModel):
    token: str
    room: str
    livekit_url: str


class EnrolmentResponse(BaseModel):
    status: str
    segments_processed: int
    message: str


class ChallengeResponse(BaseModel):
    challenge_id: str
    phrase: str
    expires_in: int  # seconds


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

    _livekit_url = cfg.livekit_public_url or f"wss://{cfg.ira_domain}/livekit"
    return LiveKitTokenResponse(
        token=jwt,
        room=cfg.livekit_room_name,
        livekit_url=_livekit_url,
    )


# ── Local TTS (browser-native voice) ──────────────────────────────────────────

class SayRequest(BaseModel):
    text: str
    voice: str | None = None   # M1–M5 / F1–F5; defaults to IRA_VOICE (F1, female)
    lang: str | None = None    # ISO 639-1; ta/te/kn/ml -> native Indic engine, else Supertonic


@router.post("/say")
async def say(req: SayRequest, _user: str = Depends(require_auth)):
    """Synthesise `text` to a WAV and return it as audio/wav.

    Picks the TTS engine by language: Tamil/Telugu/Kannada/Malayalam use the native
    Indic engine (fail-soft to Supertonic), everything else (incl. Hindi) uses the
    on-device Supertonic engine (female F1 default). Browser-native path — no LiveKit,
    no cloud. `require_auth` bypasses the token in DEV_MODE and enforces it otherwise.
    """
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="`text` must not be empty.")

    voice = req.voice or os.getenv("IRA_VOICE", "F1")
    lang = req.lang or "en"
    steps = int(os.getenv("IRA_TTS_STEPS", "6"))   # low = fast time-to-first-audio

    # Lazy import: the synth engines pull numpy/scipy/supertonic/torch and are only
    # needed on the voice host — keep them out of module import so the route loads
    # (and its sibling endpoints test) without those heavy deps.
    try:
        from voice.tts_factory import synthesize_say
    except Exception as e:  # noqa: BLE001
        logger.error(f"TTS engine module unavailable: {e}")
        raise HTTPException(status_code=503, detail="On-device TTS engine unavailable.")

    # Synthesis is CPU/GPU-bound and synchronous — run it off the event loop.
    wav_bytes = await run_in_threadpool(synthesize_say, text, lang=lang, voice=voice, steps=steps)
    if not wav_bytes:
        raise HTTPException(status_code=503, detail="TTS synthesis failed or produced no audio.")

    return Response(content=wav_bytes, media_type="audio/wav")


# ── Local STT (sovereign) + owner gate ────────────────────────────────────────

class TranscribeResponse(BaseModel):
    text: str
    is_owner: bool


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(
    audio: UploadFile = File(..., description="Recorded utterance (webm/opus or WAV)."),
    _user: str = Depends(require_auth),
):
    """Transcribe an uploaded utterance locally with faster-whisper (sovereign — the
    audio never leaves the box) and, when biometrics are active (i.e. NOT DEV_MODE),
    run the ECAPA owner-gate on the same audio.

    Returns the transcript and whether the speaker is the enrolled owner. DEV_MODE →
    is_owner=True (gate bypassed). Non-owner / no profile / low confidence / model
    unavailable → is_owner=False (fail closed).
    """
    blob = await audio.read()
    if not blob:
        raise HTTPException(status_code=400, detail="No audio uploaded.")

    # Lazy import: faster-whisper + PyAV are heavy and only on the voice host — keep
    # them out of module import so this route loads (and tests) without them.
    try:
        from voice.stt import transcribe_audio_bytes
    except Exception as e:  # noqa: BLE001
        logger.error(f"Local STT engine unavailable: {e}")
        raise HTTPException(status_code=503, detail="Local STT engine unavailable.")

    try:
        text, _lang, _conf, pcm16 = await run_in_threadpool(transcribe_audio_bytes, blob)
    except Exception as e:  # noqa: BLE001 — undecodable/corrupt audio
        logger.error(f"Transcription failed: {e}")
        raise HTTPException(status_code=422, detail="Could not decode or transcribe the audio.")

    cfg = get_settings()
    if cfg.dev_mode:
        is_owner = True
    else:
        # Fail-closed ECAPA owner check on the same 16kHz PCM the STT decoded.
        from voice.gate import gate_from_audio
        decision = await gate_from_audio(pcm16, session_id="voice_transcribe")
        is_owner = bool(decision["is_owner"])

    return TranscribeResponse(text=text, is_owner=is_owner)


# ── Anti-replay challenge ─────────────────────────────────────────────────────

# A pool of short, unambiguous phrases for the user to speak during enrolment.
# Having variety means the phrase cannot be pre-recorded.
_CHALLENGE_PHRASES = [
    "IRA authenticate now",
    "voice lock open",
    "secure access granted",
    "identity confirm",
    "biometric verify",
    "owner access code",
    "unlock voice gate",
    "speak to proceed",
]


@router.get("/challenge", response_model=ChallengeResponse)
async def get_voice_challenge(_user: str = Depends(require_auth)):
    """
    Issue a one-time anti-replay challenge phrase. (Fix #36)

    The challenge is a random UUID stored in Redis with a 60-second TTL.
    The caller must include the ``challenge_id`` when submitting enrolment audio.
    The challenge is consumed (deleted) on first use, so a recorded replay of an
    earlier enrolment session will fail with 409 Conflict.
    """
    cfg = get_settings()
    if _user != cfg.ira_admin_username:
        raise HTTPException(
            status_code=403,
            detail="Only the system administrator may request a biometric challenge.",
        )

    challenge_id = str(uuid.uuid4())
    phrase = secrets.choice(_CHALLENGE_PHRASES)

    try:
        from utils.redis_client import get_redis
        redis = get_redis()
        await redis.setex(f"bio:challenge:{challenge_id}", _CHALLENGE_TTL, phrase)
    except Exception as e:
        logger.error(f"Could not store biometric challenge in Redis: {e}")
        raise HTTPException(
            status_code=503,
            detail="Challenge service unavailable — Redis connection failed.",
        )

    logger.info(f"Issued biometric challenge {challenge_id} to user '{_user}'")
    return ChallengeResponse(
        challenge_id=challenge_id,
        phrase=phrase,
        expires_in=_CHALLENGE_TTL,
    )


async def _consume_challenge(challenge_id: str) -> None:
    """
    Verify a challenge exists (not expired, not already used) and consume it.
    Raises HTTPException on failure.
    """
    try:
        from utils.redis_client import get_redis
        redis = get_redis()
        key = f"bio:challenge:{challenge_id}"
        # Atomic check-and-delete: returns the value if it existed, None if not
        phrase = await redis.getdel(key)
        if phrase is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Challenge not found or already used. "
                    "Request a fresh challenge from GET /voice/challenge."
                ),
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Could not verify biometric challenge in Redis: {e}")
        raise HTTPException(
            status_code=503,
            detail="Challenge verification failed — Redis connection error.",
        )


# ── Biometric voice enrolment ─────────────────────────────────────────────────

@router.post("/enroll", response_model=EnrolmentResponse)
async def enroll_voice(
    audio_files: list[UploadFile] = File(
        ...,
        description="3–10 WAV/PCM audio files (16kHz mono) of the owner speaking.",
    ),
    challenge_id: str = Form(
        ...,
        description=(
            "One-time challenge ID obtained from GET /voice/challenge. "
            "Prevents replay attacks — the challenge is consumed on use."
        ),
    ),
    _user: str = Depends(require_auth),
):
    """
    Owner voice enrolment endpoint.

    Submit 3–10 audio segments (≥3 seconds each, 16kHz mono PCM/WAV)
    together with a one-time ``challenge_id`` from GET /voice/challenge.

    Fix #36 (anti-replay): the challenge_id is consumed on first use so that
    a previously recorded enrolment session cannot be replayed by an attacker.

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

    # Consume the anti-replay challenge before processing any audio (#36)
    await _consume_challenge(challenge_id)

    if len(audio_files) < 3:
        raise HTTPException(status_code=400, detail="At least 3 audio files are required for a reliable voice profile. Submit 3–10 segments.")
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
        # Validate WAV format: must be 16kHz, mono, 16-bit PCM
        if audio_bytes[:4] == b"RIFF":
            import wave, io as _io
            try:
                with wave.open(_io.BytesIO(audio_bytes)) as wf:
                    sr = wf.getframerate()
                    ch = wf.getnchannels()
                    sw = wf.getsampwidth()
                    if sr != 16000:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Audio file '{f.filename}' must be 16kHz (got {sr} Hz). "
                                   "Resample with: ffmpeg -ar 16000 -ac 1 input.wav output.wav",
                        )
                    if ch != 1:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Audio file '{f.filename}' must be mono (got {ch} channels). "
                                   "Downmix with: ffmpeg -ac 1 input.wav output.wav",
                        )
                    if sw != 2:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Audio file '{f.filename}' must be 16-bit PCM (got {sw*8}-bit).",
                        )
                    audio_bytes = wf.readframes(wf.getnframes())
            except HTTPException:
                raise
            except Exception:
                # Fallback: skip standard 44-byte header
                audio_bytes = audio_bytes[44:]
        else:
            raise HTTPException(
                status_code=400,
                detail=f"File '{f.filename}' is not a valid WAV file. "
                       "Only 16kHz mono 16-bit WAV files are accepted for enrolment.",
            )

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
