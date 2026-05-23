"""
IRA Image Generation + Editing — Grok Imagine parity.

Supports two backends (configure one in .env):
  1. Stable Diffusion WebUI (Automatic1111) — set IMAGE_GEN_URL to the API base
     e.g., IMAGE_GEN_URL=http://localhost:7860
  2. Replicate API (Flux Schnell, SDXL, InstructPix2Pix) — set REPLICATE_API_TOKEN

Falls back gracefully with a 503 and clear setup instructions if neither is set.

POST /image/generate  — text prompt → base64 PNG
POST /image/edit      — base64 image + instruction → base64 PNG
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.middleware.auth import require_auth

router = APIRouter(prefix="/image", tags=["image"])
logger = logging.getLogger("ira.image_gen")

_IMAGE_GEN_URL = os.getenv("IMAGE_GEN_URL", "").rstrip("/")
_REPLICATE_TOKEN = os.getenv("REPLICATE_API_TOKEN", "")
_FLUX_MODEL = os.getenv("FLUX_MODEL", "black-forest-labs/flux-schnell")


# ── Request models ─────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    negative_prompt: str = ""
    width: int = Field(1024, ge=256, le=2048)
    height: int = Field(1024, ge=256, le=2048)
    steps: int = Field(20, ge=1, le=50)
    guidance_scale: float = Field(7.5, ge=1.0, le=30.0)
    seed: int = -1


class EditRequest(BaseModel):
    image_b64: str = Field(..., description="Base64-encoded source image")
    instruction: str = Field(..., min_length=1, max_length=1000)
    strength: float = Field(0.75, ge=0.1, le=1.0)


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/generate")
async def generate_image(req: GenerateRequest, _user: str = Depends(require_auth)):
    """
    Generate an image from a text prompt.
    Returns: {"image_b64": "<base64 PNG>", "mime_type": "image/png", "prompt": "..."}
    """
    if _IMAGE_GEN_URL:
        image_b64 = await _generate_sd_webui(req)
    elif _REPLICATE_TOKEN:
        image_b64 = await _generate_replicate(req)
    else:
        raise HTTPException(
            status_code=503,
            detail=(
                "Image generation is not configured. "
                "Add IMAGE_GEN_URL (Stable Diffusion WebUI URL) "
                "or REPLICATE_API_TOKEN to your .env file to enable it."
            ),
        )

    return {"image_b64": image_b64, "mime_type": "image/png", "prompt": req.prompt}


@router.post("/edit")
async def edit_image(req: EditRequest, _user: str = Depends(require_auth)):
    """
    Edit an image using a text instruction (InstructPix2Pix style).
    Returns: {"image_b64": "<base64 PNG>", "mime_type": "image/png"}
    """
    if _IMAGE_GEN_URL:
        image_b64 = await _edit_sd_webui(req)
    elif _REPLICATE_TOKEN:
        image_b64 = await _edit_replicate(req)
    else:
        raise HTTPException(
            status_code=503,
            detail=(
                "Image editing is not configured. "
                "Add IMAGE_GEN_URL or REPLICATE_API_TOKEN to your .env file."
            ),
        )

    return {"image_b64": image_b64, "mime_type": "image/png"}


# ── Stable Diffusion WebUI backend ─────────────────────────────────────────────

async def _generate_sd_webui(req: GenerateRequest) -> str:
    """Call Automatic1111 SD WebUI /sdapi/v1/txt2img endpoint."""
    import httpx
    payload: dict[str, Any] = {
        "prompt": req.prompt,
        "negative_prompt": req.negative_prompt or "ugly, blurry, low quality, watermark",
        "width": req.width,
        "height": req.height,
        "steps": req.steps,
        "cfg_scale": req.guidance_scale,
        "seed": req.seed if req.seed >= 0 else -1,
        "sampler_name": "DPM++ 2M Karras",
        "batch_size": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{_IMAGE_GEN_URL}/sdapi/v1/txt2img", json=payload)
            resp.raise_for_status()
            data = resp.json()
        images = data.get("images", [])
        if not images:
            raise HTTPException(status_code=500, detail="SD WebUI returned no images")
        return images[0]  # already base64 PNG
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"SD WebUI error: {e}")


async def _edit_sd_webui(req: EditRequest) -> str:
    """Call SD WebUI /sdapi/v1/img2img for InstructPix2Pix-style editing."""
    import httpx
    payload: dict[str, Any] = {
        "prompt": req.instruction,
        "init_images": [req.image_b64],
        "denoising_strength": req.strength,
        "steps": 20,
        "cfg_scale": 7.5,
        "sampler_name": "DPM++ 2M Karras",
        "batch_size": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{_IMAGE_GEN_URL}/sdapi/v1/img2img", json=payload)
            resp.raise_for_status()
            data = resp.json()
        images = data.get("images", [])
        if not images:
            raise HTTPException(status_code=500, detail="SD WebUI returned no images")
        return images[0]
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"SD WebUI error: {e}")


# ── Replicate backend (Flux / InstructPix2Pix) ─────────────────────────────────

async def _replicate_poll(prediction_url: str, headers: dict, timeout_s: int = 120) -> str:
    """Poll a Replicate prediction until complete and return the output URL."""
    import httpx
    async with httpx.AsyncClient(timeout=15) as client:
        for _ in range(timeout_s // 3):
            await asyncio.sleep(3)
            poll = await client.get(prediction_url, headers=headers)
            poll.raise_for_status()
            status_data = poll.json()
            status = status_data.get("status")
            if status == "succeeded":
                output = status_data.get("output")
                return output[0] if isinstance(output, list) else output
            elif status == "failed":
                raise HTTPException(
                    status_code=500,
                    detail=f"Replicate job failed: {status_data.get('error')}",
                )
    raise HTTPException(status_code=504, detail="Replicate job timed out")


async def _download_to_b64(url: str) -> str:
    """Download an image URL and return base64-encoded bytes."""
    import httpx
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return base64.b64encode(resp.content).decode()


async def _generate_replicate(req: GenerateRequest) -> str:
    """Use Replicate Flux Schnell for fast, high-quality image generation."""
    import httpx
    headers = {
        "Authorization": f"Token {_REPLICATE_TOKEN}",
        "Content-Type": "application/json",
    }
    # Flux Schnell via Replicate deployments API
    payload = {
        "input": {
            "prompt": req.prompt,
            "width": req.width,
            "height": req.height,
            "num_inference_steps": min(req.steps, 4),  # Flux Schnell max is 4
            "seed": req.seed if req.seed >= 0 else None,
        }
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://api.replicate.com/v1/models/{_FLUX_MODEL}/predictions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            prediction = resp.json()

        output_url = await _replicate_poll(prediction["urls"]["get"], headers)
        return await _download_to_b64(output_url)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Replicate error: {e}")


async def _edit_replicate(req: EditRequest) -> str:
    """Use Replicate InstructPix2Pix for image editing."""
    import httpx
    headers = {
        "Authorization": f"Token {_REPLICATE_TOKEN}",
        "Content-Type": "application/json",
    }
    data_url = f"data:image/png;base64,{req.image_b64}"
    payload = {
        "version": (
            "timbrooks/instruct-pix2pix:"
            "30c1d0b916a6f8efce20493f5d61ee27491ab2a60437c13c588468b9810ec23f"
        ),
        "input": {
            "image": data_url,
            "prompt": req.instruction,
            "image_guidance_scale": 1.5,
            "guidance_scale": 7.5,
            "num_inference_steps": 20,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.replicate.com/v1/predictions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            prediction = resp.json()

        output_url = await _replicate_poll(prediction["urls"]["get"], headers)
        return await _download_to_b64(output_url)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Replicate edit error: {e}")
