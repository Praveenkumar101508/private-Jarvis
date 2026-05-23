"""
IRA Audio & Music Generation — Feature #6.

Generate music, voice, speech, and sound effects from chat.

POST /audio/generate   — text-to-music / sound effects via Replicate (SSE)
POST /audio/tts        — text-to-speech synthesis
POST /audio/transcribe — audio file → transcript (Whisper)

Provider chain:
  1. Replicate API (REPLICATE_API_TOKEN) — MusicGen, MusicGen-Stereo, Bark TTS
  2. Graceful 503 with setup instructions if not configured

Trigger phrases:
  "generate music...", "create a song...", "compose music for...",
  "make a soundtrack...", "generate a sound effect...", "create audio...",
  "make background music...", "compose a melody...", "generate speech...",
  "voice over for...", "narrate this...", "transcribe this audio..."
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
import os
import re
import time
import uuid
from typing import Optional, Literal

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from api.middleware.auth import require_auth
from config import get_settings

router = APIRouter(prefix="/audio", tags=["audio"])
logger = logging.getLogger("ira.audio_gen")

# Replicate model IDs
_MUSIC_GEN_MODEL = os.getenv("REPLICATE_MUSIC_MODEL", "meta/musicgen:671ac645ce5e552cc63a54a2bbff63fcf798043055d2dac5fc9e36a837eedcfb")
_MUSIC_STEREO_MODEL = os.getenv("REPLICATE_MUSIC_STEREO_MODEL", "meta/musicgen-stereo-melody-large")
_BARK_TTS_MODEL = os.getenv("REPLICATE_BARK_MODEL", "suno-ai/bark:b76242b40d67c76ab6742e987628a2a9ac019e11d56ab96c4e91ce03b79b2787")
_SOUND_EFFECT_MODEL = os.getenv("REPLICATE_SFX_MODEL", "haoheliu/audio-ldm:b61392adecdd660326fc9cfc5398182437dbe5e97b5decfb36e1a36de68b5b95")

# Trigger detection
_AUDIO_GEN_RE = re.compile(
    r"\b(generate\s+(music|a?\s*song|audio|a?\s*melody|a?\s*soundtrack|sound.?effect|speech)|"
    r"create\s+(music|a?\s*song|a?\s*melody|a?\s*soundtrack|sound.?effect|audio)|"
    r"compose\s+(music|a?\s*song|a?\s*melody|a?\s*soundtrack)|"
    r"make\s+(music|a?\s*song|a?\s*soundtrack|background.?music|sound.?effect)|"
    r"(voice.?over|narrate|text.?to.?speech|tts)\s+(this|for)|"
    r"produce\s+(music|audio|a?\s*track))\b",
    re.I,
)
_TRANSCRIBE_RE = re.compile(
    r"\b(transcribe|transcript.?of|what.?(?:does|did)\s+(?:this|the)\s+audio|"
    r"convert\s+audio\s+to\s+text)\b",
    re.I,
)


def is_audio_gen_request(query: str) -> bool:
    return bool(_AUDIO_GEN_RE.search(query))


def is_transcribe_request(query: str) -> bool:
    return bool(_TRANSCRIBE_RE.search(query))


def _detect_audio_type(query: str) -> Literal["music", "sfx", "tts"]:
    q = query.lower()
    if any(w in q for w in ("voice over", "voice-over", "narrate", "tts", "text to speech", "speak", "say")):
        return "tts"
    if any(w in q for w in ("sound effect", "sfx", "ambient", "noise", "explosion", "rain", "footstep")):
        return "sfx"
    return "music"


# ── Request models ────────────────────────────────────────────────────────────

class AudioGenRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    duration: int = Field(default=15, ge=5, le=60, description="Duration in seconds")
    audio_type: Optional[Literal["music", "sfx", "tts"]] = None
    voice: Optional[str] = Field(default="v2/en_speaker_6", description="Bark voice preset for TTS")
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


# ── Replicate audio generation ────────────────────────────────────────────────

async def _generate_replicate_audio(req: AudioGenRequest, audio_type: str) -> str:
    """Call Replicate to generate audio. Returns audio URL."""
    token = get_settings().replicate_api_token
    if not token:
        raise HTTPException(
            status_code=503,
            detail=(
                "Audio generation not configured. "
                "Add REPLICATE_API_TOKEN to .env to enable it.\n"
                "MusicGen is ~$0.005/second. Sign up at https://replicate.com"
            ),
        )

    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json",
        "Prefer": "wait=300",
    }

    if audio_type == "music":
        model = _MUSIC_GEN_MODEL
        input_payload = {
            "prompt": req.prompt,
            "duration": req.duration,
            "model_version": "stereo-melody-large",
            "output_format": "mp3",
            "normalization_strategy": "peak",
        }
    elif audio_type == "sfx":
        model = _SOUND_EFFECT_MODEL
        input_payload = {
            "text": req.prompt,
            "duration_in_seconds": min(req.duration, 30),
            "guidance_scale": 2.5,
        }
    else:  # tts
        model = _BARK_TTS_MODEL
        input_payload = {
            "prompt": req.prompt[:500],
            "history_prompt": req.voice or "v2/en_speaker_6",
        }

    async with httpx.AsyncClient(timeout=360.0) as client:
        resp = await client.post(
            f"https://api.replicate.com/v1/predictions",
            headers=headers,
            json={"version": model.split(":")[-1] if ":" in model else None,
                  "model": model if ":" not in model else None,
                  "input": input_payload},
        )
        resp.raise_for_status()
        prediction = resp.json()
        pred_id = prediction["id"]

        # Poll until complete
        for _ in range(90):  # max 7.5 min
            status = prediction.get("status")
            if status in ("succeeded", "failed", "canceled"):
                break
            await asyncio.sleep(5)
            poll = await client.get(
                f"https://api.replicate.com/v1/predictions/{pred_id}",
                headers=headers,
            )
            prediction = poll.json()

        if prediction.get("status") != "succeeded":
            raise HTTPException(
                status_code=500,
                detail=f"Audio generation failed: {prediction.get('error', 'unknown error')}",
            )

        output = prediction.get("output")
        if isinstance(output, list):
            return output[0]
        return str(output)


# ── SSE generate endpoint ─────────────────────────────────────────────────────

@router.post("/generate")
async def audio_generate(
    req: AudioGenRequest,
    _user: str = Depends(require_auth),
):
    """Generate music, sound effects, or speech from text (SSE streaming)."""
    audio_type = req.audio_type or _detect_audio_type(req.prompt)

    type_labels = {
        "music": f"🎵 music track ({req.duration}s)",
        "sfx": "🔊 sound effect",
        "tts": "🗣️ voice synthesis",
    }

    async def gen():
        t0 = time.monotonic()
        yield {"data": _json.dumps({"token": f"🎧 Generating {type_labels[audio_type]}: *{req.prompt[:60]}*…\n\nThis takes 15-60 seconds.\n"})}

        try:
            audio_url = await _generate_replicate_audio(req, audio_type)
            latency = int((time.monotonic() - t0) * 1000)

            yield {"data": _json.dumps({
                "audio_generated": True,
                "audio_url": audio_url,
                "audio_type": audio_type,
                "prompt": req.prompt,
                "duration": req.duration,
            })}
            yield {"data": _json.dumps({
                "token": (
                    f"\n✅ Audio ready! ({latency // 1000}s)\n\n"
                    f"🎧 [{type_labels[audio_type].split(' ')[1].title()}]({audio_url})"
                )
            })}
        except HTTPException as e:
            yield {"data": _json.dumps({"token": f"\n⚠️ {e.detail}"})}
        except Exception as e:
            logger.error(f"Audio generation error: {e}", exc_info=True)
            yield {"data": _json.dumps({"token": f"\n❌ Audio generation error: {str(e)[:200]}"})}

        yield {"data": _json.dumps({
            "done": True, "agent": "audio_gen",
            "latency_ms": int((time.monotonic() - t0) * 1000),
        })}

    return EventSourceResponse(gen())


# ── Text-to-speech endpoint ───────────────────────────────────────────────────

class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    voice: str = Field(default="v2/en_speaker_6")


@router.post("/tts")
async def audio_tts(
    req: TTSRequest,
    _user: str = Depends(require_auth),
):
    """Convert text to speech using Bark (SSE streaming)."""
    audio_req = AudioGenRequest(prompt=req.text, voice=req.voice, audio_type="tts")

    async def gen():
        t0 = time.monotonic()
        yield {"data": _json.dumps({"token": f"🗣️ Synthesising speech…\n"})}
        try:
            url = await _generate_replicate_audio(audio_req, "tts")
            yield {"data": _json.dumps({"audio_url": url, "audio_type": "tts"})}
            yield {"data": _json.dumps({"token": f"\n✅ Speech ready! [🔊 Play]({url})"})}
        except HTTPException as e:
            yield {"data": _json.dumps({"token": f"\n⚠️ {e.detail}"})}
        except Exception as e:
            yield {"data": _json.dumps({"token": f"\n❌ TTS error: {str(e)[:200]}"})}
        yield {"data": _json.dumps({"done": True, "agent": "audio_tts", "latency_ms": int((time.monotonic() - t0) * 1000)})}

    return EventSourceResponse(gen())


# ── Transcription endpoint ────────────────────────────────────────────────────

@router.post("/transcribe")
async def audio_transcribe(
    file: UploadFile = File(...),
    language: str = Form(default="en"),
    _user: str = Depends(require_auth),
):
    """
    Transcribe an audio file using Whisper (via Replicate or local).
    Returns SSE stream of transcript tokens.
    """
    _WHISPER_MODEL = "openai/whisper:4d50797290df2f63793a75e2a19c694db87b6c8da52b0a4929dfe87dfe5b3d7"

    audio_bytes = await file.read()
    if len(audio_bytes) > 50 * 1024 * 1024:  # 50MB limit
        raise HTTPException(status_code=413, detail="Audio file too large. Max 50MB.")

    import base64
    audio_b64 = base64.b64encode(audio_bytes).decode()
    data_url = f"data:{file.content_type or 'audio/mpeg'};base64,{audio_b64}"

    async def gen():
        t0 = time.monotonic()
        yield {"data": _json.dumps({"token": f"🎤 Transcribing audio ({len(audio_bytes)//1024}KB)…\n\n"})}

        token = get_settings().replicate_api_token
        if not token:
            yield {"data": _json.dumps({"token": "⚠️ Add REPLICATE_API_TOKEN to .env for transcription.\n"})}
            yield {"data": _json.dumps({"done": True, "agent": "audio_transcribe", "latency_ms": 0})}
            return

        try:
            headers = {"Authorization": f"Token {token}", "Content-Type": "application/json"}
            async with httpx.AsyncClient(timeout=300.0) as client:
                resp = await client.post(
                    "https://api.replicate.com/v1/predictions",
                    headers=headers,
                    json={
                        "version": _WHISPER_MODEL.split(":")[1],
                        "input": {"audio": data_url, "language": language, "model": "large-v3"},
                    },
                )
                resp.raise_for_status()
                prediction = resp.json()
                pred_id = prediction["id"]

                for _ in range(60):
                    if prediction.get("status") in ("succeeded", "failed", "canceled"):
                        break
                    await asyncio.sleep(3)
                    poll = await client.get(f"https://api.replicate.com/v1/predictions/{pred_id}", headers=headers)
                    prediction = poll.json()

                if prediction.get("status") == "succeeded":
                    output = prediction.get("output", {})
                    transcript = output.get("transcription", "") if isinstance(output, dict) else str(output)
                    yield {"data": _json.dumps({"token": f"**Transcript:**\n\n{transcript}"})}
                    yield {"data": _json.dumps({"transcript": transcript})}
                else:
                    yield {"data": _json.dumps({"token": f"❌ Transcription failed: {prediction.get('error', 'unknown')}"})}
        except Exception as e:
            yield {"data": _json.dumps({"token": f"❌ Transcription error: {str(e)[:200]}"})}

        yield {"data": _json.dumps({"done": True, "agent": "audio_transcribe", "latency_ms": int((time.monotonic() - t0) * 1000)})}

    return EventSourceResponse(gen())
