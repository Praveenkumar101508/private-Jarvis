"""
IRA Video Generation + Video Understanding — Feature #1 & #5.

Feature 1 — Video Generation:
  POST /video/generate   — text-to-video via Replicate (Wan2.1, CogVideoX, MiniMax)
  Trigger: "generate a video of...", "create a video showing...", "make a video..."

Feature 5 — Video Understanding:
  POST /video/understand — upload video, extract frames, analyse with vision model
  Trigger: "analyse this video", "what's in this video", "summarise this video"

Provider chain (same pattern as image_gen.py):
  1. Replicate API  (REPLICATE_API_TOKEN) — Wan2.1-t2v-480p or minimax/video-01
  2. Graceful 503   if not configured
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, File, Form, UploadFile, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from api.middleware.auth import require_auth
from config import get_settings

router = APIRouter(prefix="/video", tags=["video"])
logger = logging.getLogger("ira.video")

# ── Replicate model identifiers (2026 best open-source video models) ──────────
_VIDEO_GEN_MODEL = os.getenv(
    "REPLICATE_VIDEO_MODEL",
    "wan-ai/wan2.1-t2v-480p",  # Best open-source text-to-video May 2026
)
_VIDEO_IMG_MODEL = os.getenv(
    "REPLICATE_VIDEO_IMG_MODEL",
    "wan-ai/wan2.1-i2v-480p",  # Image-to-video
)

# Video trigger detection
_VIDEO_GEN_RE = re.compile(
    r"\b(generate\s+a?\s*video|create\s+a?\s*video|make\s+a?\s*video|"
    r"video\s+of|animate|text.to.video|image.to.video|"
    r"record\s+a?\s*video|produce\s+a?\s*video)\b",
    re.I,
)
_VIDEO_UNDERSTAND_RE = re.compile(
    r"\b(analys[ei]s?\s+(this\s+)?video|what.?s?\s+(in\s+)?(this\s+)?video|"
    r"summaris[ez]?\s+(this\s+)?video|watch\s+(this|the)\s+video|"
    r"describe\s+(this\s+)?video|transcribe|what\s+happen[s]?\s+in)\b",
    re.I,
)


def is_video_gen_request(query: str) -> bool:
    return bool(_VIDEO_GEN_RE.search(query))


def is_video_understand_request(query: str) -> bool:
    return bool(_VIDEO_UNDERSTAND_RE.search(query))


# ── Request models ────────────────────────────────────────────────────────────

class VideoGenRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    duration: int = Field(default=5, ge=2, le=10, description="Video duration in seconds")
    width: int = Field(default=854)
    height: int = Field(default=480)
    image_b64: Optional[str] = Field(None, description="Base64 image for image-to-video")
    mime_type: str = Field(default="image/jpeg")


# ── Replicate video generation ────────────────────────────────────────────────

async def _generate_replicate_video(req: VideoGenRequest) -> str:
    """Call Replicate API to generate a video. Returns the video URL."""
    token = get_settings().replicate_api_token
    if not token:
        raise HTTPException(
            status_code=503,
            detail=(
                "Video generation not configured. "
                "Add REPLICATE_API_TOKEN to .env to enable it.\n"
                "Sign up at https://replicate.com — the Wan2.1 model is ~$0.02 per video."
            ),
        )

    model = _VIDEO_GEN_MODEL
    input_payload: dict = {
        "prompt": req.prompt,
        "num_frames": req.duration * 8,  # Wan2.1: ~8 fps
        "width": req.width,
        "height": req.height,
        "guidance_scale": 7.5,
        "num_inference_steps": 30,
    }

    # Image-to-video if source image provided
    if req.image_b64:
        model = _VIDEO_IMG_MODEL
        data_url = f"data:{req.mime_type};base64,{req.image_b64}"
        input_payload["image"] = data_url
        input_payload.pop("num_frames", None)

    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json",
        "Prefer": "wait=120",  # Wait up to 120s for the result
    }

    async with httpx.AsyncClient(timeout=180.0) as client:
        # Create prediction
        resp = await client.post(
            f"https://api.replicate.com/v1/models/{model}/predictions",
            headers=headers,
            json={"input": input_payload},
        )
        resp.raise_for_status()
        prediction = resp.json()

        pred_id = prediction["id"]
        # Poll until complete (Prefer: wait may handle it)
        for _ in range(60):  # max 5 min
            if prediction.get("status") in ("succeeded", "failed", "canceled"):
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
                detail=f"Video generation failed: {prediction.get('error', 'unknown error')}",
            )

        output = prediction.get("output")
        if isinstance(output, list):
            return output[0]
        return str(output)


# ── Video generation SSE endpoint ────────────────────────────────────────────

import json as _json

@router.post("/generate")
async def video_generate(
    req: VideoGenRequest,
    _user: str = Depends(require_auth),
):
    """Generate a video from text or image → video (SSE streaming)."""

    async def gen():
        t0 = time.monotonic()
        yield {"data": _json.dumps({"token": f"🎬 Generating your video: *{req.prompt[:80]}*…\n\nThis takes 30-90 seconds with Wan2.1.\n"})}
        try:
            video_url = await _generate_replicate_video(req)
            latency = int((time.monotonic() - t0) * 1000)
            yield {"data": _json.dumps({
                "video_generated": True,
                "video_url": video_url,
                "prompt": req.prompt,
                "duration": req.duration,
            })}
            yield {"data": _json.dumps({
                "token": f"\n✅ Video ready! ({latency // 1000}s)"
            })}
        except HTTPException as e:
            yield {"data": _json.dumps({"token": f"\n⚠️ {e.detail}"})}
        except Exception as e:
            yield {"data": _json.dumps({"token": f"\n❌ Video generation error: {str(e)[:200]}"})}

        yield {"data": _json.dumps({"done": True, "agent": "video_gen", "latency_ms": int((time.monotonic() - t0) * 1000)})}

    return EventSourceResponse(gen())


# ── Video understanding ───────────────────────────────────────────────────────

def _extract_frames_ffmpeg(video_bytes: bytes, max_frames: int = 8) -> list[str]:
    """
    Extract evenly-spaced frames from a video using ffmpeg subprocess.
    Returns list of base64-encoded JPEG frames.
    Falls back gracefully if ffmpeg is not installed.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        video_path = Path(tmpdir) / "input.mp4"
        video_path.write_bytes(video_bytes)
        frame_pattern = Path(tmpdir) / "frame_%03d.jpg"

        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-i", str(video_path),
                    "-vf", f"fps=1/2",        # 1 frame every 2 seconds
                    "-frames:v", str(max_frames),
                    "-q:v", "5",
                    str(frame_pattern),
                    "-y", "-loglevel", "error",
                ],
                capture_output=True,
                timeout=60,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            # ffmpeg not installed or timed out
            return []

        frames_b64 = []
        for f in sorted(Path(tmpdir).glob("frame_*.jpg"))[:max_frames]:
            frames_b64.append(base64.b64encode(f.read_bytes()).decode())
        return frames_b64


@router.post("/understand")
async def video_understand(
    file: UploadFile = File(...),
    message: str = Form(default="Analyse and summarise this video. What is happening? Who is in it?"),
    session_id: str = Form(default_factory=lambda: str(uuid.uuid4())),
    _user: str = Depends(require_auth),
):
    """
    Upload a video file → extract frames → analyse with vision model.
    Returns an SSE stream of analysis tokens.
    """
    from utils.llm import stream_tokens
    from config import get_settings as _cfg

    cfg = _cfg()
    video_bytes = await file.read()
    if len(video_bytes) > 100 * 1024 * 1024:  # 100MB limit
        raise HTTPException(status_code=413, detail="Video file too large. Max 100MB.")

    frames = _extract_frames_ffmpeg(video_bytes, max_frames=8)

    async def understand_gen():
        t0 = time.monotonic()

        if not frames:
            # No ffmpeg — use text-only description
            yield {"data": _json.dumps({"token": "⚠️ ffmpeg not installed — analysing video metadata only.\n\n"})}
            yield {"data": _json.dumps({"token": f"File: {file.filename}, Size: {len(video_bytes)//1024}KB\n\n"})}
            yield {"data": _json.dumps({"token": "Install ffmpeg in Docker for full video frame analysis: `apt-get install ffmpeg`\n"})}
            yield {"data": _json.dumps({"done": True, "agent": "video_understand", "latency_ms": 0})}
            return

        yield {"data": _json.dumps({"token": f"🎬 Extracted {len(frames)} frames from video. Analysing…\n\n"})}

        vision_url = cfg.vllm_vision_url
        if vision_url:
            # Build multimodal message with all frames
            content: list = [{"type": "text", "text": message}]
            for i, b64 in enumerate(frames[:5]):  # max 5 frames to stay under token limits
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "low"},
                })
            content.append({"type": "text", "text": f"\n(Above are {len(frames)} evenly-spaced frames from the video)"})

            msgs = [
                {"role": "system", "content": "You are a video analysis expert. Analyse the provided video frames and answer the user's question in detail."},
                {"role": "user", "content": content},
            ]
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=cfg.vllm_api_key, base_url=vision_url)
            try:
                stream = await client.chat.completions.create(
                    model=cfg.vllm_vision_model, messages=msgs,  # type: ignore
                    stream=True, max_tokens=2048, temperature=0.3,
                )
                async for chunk in stream:
                    tok = chunk.choices[0].delta.content or ""
                    if tok:
                        yield {"data": _json.dumps({"token": tok})}
            except Exception as e:
                yield {"data": _json.dumps({"token": f"Vision model error: {e}\n\n"})}
        else:
            # No vision model — describe frames using text model
            frame_desc = f"[{len(frames)} frames extracted from video: {file.filename}]"
            msgs = [
                {"role": "system", "content": "You are an AI assistant. The user uploaded a video and frames were extracted. Describe what you can infer from the provided information."},
                {"role": "user", "content": f"{message}\n\nVideo: {file.filename} ({len(video_bytes)//1024}KB)\n{frame_desc}\n\nNote: Set VLLM_VISION_URL in .env for full multimodal video analysis with actual frame images."},
            ]
            async for tok in stream_tokens(msgs, use_deep=False):
                yield {"data": _json.dumps({"token": tok})}

        latency = int((time.monotonic() - t0) * 1000)
        yield {"data": _json.dumps({"done": True, "agent": "video_understand", "latency_ms": latency})}

    return EventSourceResponse(understand_gen())
