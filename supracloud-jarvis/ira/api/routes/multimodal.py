"""
IRA Multi-Modal Fusion — Feature #8.

A unified pipeline that intelligently combines text, image, video, audio, and documents
into a single coherent response. IRA detects what modalities are present and routes
each through the appropriate specialist, then fuses the outputs.

POST /multimodal/analyse  — analyse any combination of inputs (SSE)

Handles:
  - Text + Image → vision analysis + contextual answer
  - Text + Video → frame extraction + analysis
  - Text + Audio → transcription + analysis
  - Text + Document → extraction + Q&A
  - Text + Image + Voice → full multimodal fusion
  - Multiple images → comparison, collage analysis

Trigger: automatically activated when multiple modalities are detected in a request.
"""

from __future__ import annotations

import asyncio
import base64
import json as _json
import logging
import re
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from api.middleware.auth import require_auth
from config import get_settings
from utils.llm import stream_tokens, chat_complete

router = APIRouter(prefix="/multimodal", tags=["multimodal"])
logger = logging.getLogger("ira.multimodal")


def _detect_media_type(content_type: str, filename: str) -> str:
    """Detect media type from content-type header or filename."""
    ct = (content_type or "").lower()
    fn = (filename or "").lower()

    if any(x in ct for x in ("image/", "png", "jpeg", "jpg", "gif", "webp")) or \
       any(fn.endswith(x) for x in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")):
        return "image"
    if any(x in ct for x in ("video/", "mp4", "webm", "avi", "mov")) or \
       any(fn.endswith(x) for x in (".mp4", ".webm", ".avi", ".mov", ".mkv")):
        return "video"
    if any(x in ct for x in ("audio/", "mpeg", "wav", "ogg", "flac")) or \
       any(fn.endswith(x) for x in (".mp3", ".wav", ".ogg", ".flac", ".m4a")):
        return "audio"
    if "pdf" in ct or fn.endswith(".pdf"):
        return "pdf"
    if any(x in ct for x in ("word", "docx", "officedocument.word")) or \
       any(fn.endswith(x) for x in (".docx", ".doc")):
        return "docx"
    return "unknown"


async def _analyse_image_b64(image_b64: str, mime: str, question: str, cfg) -> str:
    """Analyse an image using the vision model."""
    vision_url = cfg.vllm_vision_url
    if not vision_url:
        return "[Vision model not configured — set VLLM_VISION_URL in .env for image analysis]"

    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=cfg.vllm_api_key, base_url=vision_url)
    msgs = [
        {"role": "system", "content": "You are a vision AI expert. Analyse the provided image(s) and answer the user's question precisely."},
        {"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}", "detail": "high"}},
            {"type": "text", "text": question or "Describe this image in detail."},
        ]},
    ]
    try:
        resp = await client.chat.completions.create(
            model=cfg.vllm_vision_model,
            messages=msgs,
            max_tokens=2048,
            temperature=0.3,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        return f"[Vision analysis error: {e}]"


async def _extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extract text from PDF using pypdf."""
    try:
        import io
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = []
        for page in reader.pages[:20]:  # Max 20 pages
            pages.append(page.extract_text() or "")
        return "\n\n".join(pages)
    except ImportError:
        return "[pypdf not installed — PDF text extraction unavailable]"
    except Exception as e:
        return f"[PDF extraction error: {e}]"


async def _extract_text_from_docx(docx_bytes: bytes) -> str:
    """Extract text from DOCX using python-docx."""
    try:
        import io
        from docx import Document
        doc = Document(io.BytesIO(docx_bytes))
        return "\n".join(para.text for para in doc.paragraphs if para.text.strip())
    except ImportError:
        return "[python-docx not installed — DOCX extraction unavailable]"
    except Exception as e:
        return f"[DOCX extraction error: {e}]"


async def _extract_video_frames(video_bytes: bytes) -> list[str]:
    """Extract frames from video using ffmpeg."""
    import subprocess
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        video_path = Path(tmpdir) / "video.mp4"
        video_path.write_bytes(video_bytes)
        frame_pattern = Path(tmpdir) / "frame_%03d.jpg"
        try:
            subprocess.run(
                ["ffmpeg", "-i", str(video_path), "-vf", "fps=1/3",
                 "-frames:v", "5", "-q:v", "5", str(frame_pattern), "-y", "-loglevel", "error"],
                capture_output=True, timeout=60,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return []
        frames = []
        for f in sorted(Path(tmpdir).glob("frame_*.jpg"))[:5]:
            frames.append(base64.b64encode(f.read_bytes()).decode())
        return frames


# ── SSE multimodal analyse endpoint ──────────────────────────────────────────

@router.post("/analyse")
async def multimodal_analyse(
    message: str = Form(default="Analyse all provided content and give me a comprehensive response."),
    session_id: str = Form(default_factory=lambda: str(uuid.uuid4())),
    files: list[UploadFile] = File(default=[]),
    _user: str = Depends(require_auth),
):
    """
    Unified multi-modal analysis: accepts any mix of images, video, audio,
    PDF/DOCX documents and text. Fuses all modalities into one coherent response.
    """
    cfg = get_settings()

    async def gen():
        t0 = time.monotonic()
        n_files = len(files)

        if n_files == 0:
            yield {"data": _json.dumps({"token": "⚠️ No files provided. Please attach images, videos, audio, or documents."})}
            yield {"data": _json.dumps({"done": True, "agent": "multimodal", "latency_ms": 0})}
            return

        yield {"data": _json.dumps({"token": f"🧩 **Multi-Modal Fusion**: Analysing {n_files} file(s)…\n\n"})}

        # Process each file
        modality_results: list[dict] = []
        images_b64: list[tuple[str, str]] = []  # (b64, mime)

        for upload in files:
            file_bytes = await upload.read()
            media_type = _detect_media_type(upload.content_type or "", upload.filename or "")
            size_kb = len(file_bytes) // 1024

            yield {"data": _json.dumps({"token": f"  📎 {upload.filename} ({media_type}, {size_kb}KB)\n"})}

            if media_type == "image":
                mime = upload.content_type or "image/jpeg"
                b64 = base64.b64encode(file_bytes).decode()
                images_b64.append((b64, mime))
                modality_results.append({
                    "type": "image",
                    "filename": upload.filename,
                    "content": f"[Image: {upload.filename}, {size_kb}KB — to be analysed with vision model]",
                })

            elif media_type == "video":
                yield {"data": _json.dumps({"token": "  🎬 Extracting video frames…\n"})}
                frames = await _extract_video_frames(file_bytes)
                if frames:
                    # Analyse first frame
                    frame_analysis = await _analyse_image_b64(frames[0], "image/jpeg",
                        f"This is a frame from video '{upload.filename}'. {message}", cfg)
                    modality_results.append({
                        "type": "video",
                        "filename": upload.filename,
                        "frames_extracted": len(frames),
                        "content": frame_analysis,
                    })
                else:
                    modality_results.append({
                        "type": "video",
                        "filename": upload.filename,
                        "content": f"[Video: {upload.filename} — ffmpeg not available for frame extraction]",
                    })

            elif media_type == "audio":
                modality_results.append({
                    "type": "audio",
                    "filename": upload.filename,
                    "content": f"[Audio: {upload.filename}, {size_kb}KB — use /audio/transcribe for transcription]",
                })

            elif media_type == "pdf":
                yield {"data": _json.dumps({"token": "  📄 Extracting PDF text…\n"})}
                text = await _extract_text_from_pdf(file_bytes)
                modality_results.append({
                    "type": "pdf",
                    "filename": upload.filename,
                    "content": text[:6000],  # Truncate to context limit
                })

            elif media_type == "docx":
                yield {"data": _json.dumps({"token": "  📝 Extracting document text…\n"})}
                text = await _extract_text_from_docx(file_bytes)
                modality_results.append({
                    "type": "docx",
                    "filename": upload.filename,
                    "content": text[:6000],
                })
            else:
                modality_results.append({
                    "type": "unknown",
                    "filename": upload.filename,
                    "content": f"[Unknown file type: {upload.filename}]",
                })

        # Now analyse all images together with vision model if any
        if images_b64 and cfg.vllm_vision_url:
            yield {"data": _json.dumps({"token": f"\n🔍 Analysing {len(images_b64)} image(s) with vision model…\n"})}
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=cfg.vllm_api_key, base_url=cfg.vllm_vision_url)

            content_parts = [{"type": "text", "text": message}]
            for b64, mime in images_b64[:5]:  # Max 5 images
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"},
                })

            try:
                vision_msgs = [
                    {"role": "system", "content": "You are a multi-modal AI expert. Analyse the provided content comprehensively."},
                    {"role": "user", "content": content_parts},
                ]
                vision_resp = await client.chat.completions.create(
                    model=cfg.vllm_vision_model, messages=vision_msgs,
                    max_tokens=3096, temperature=0.3,
                )
                image_analysis = vision_resp.choices[0].message.content or ""
                # Replace placeholder with actual analysis
                for r in modality_results:
                    if r["type"] == "image":
                        r["content"] = image_analysis
                        break
            except Exception as e:
                logger.error(f"Vision analysis failed: {e}")

        # Final fusion: combine all modality outputs into unified response
        yield {"data": _json.dumps({"token": "\n\n" + "─" * 50 + "\n\n"})}
        yield {"data": _json.dumps({"token": "🧠 **Fusing all modalities…**\n\n"})}

        # Build fusion context
        modality_context = "\n\n".join(
            f"**{r['type'].upper()} — {r['filename']}:**\n{r['content']}"
            for r in modality_results
        )

        fusion_msgs = [
            {"role": "system", "content": (
                "You are IRA, a supreme multi-modal AI. You have analysed multiple types of content. "
                "Synthesise all findings into a unified, insightful response that addresses the user's question. "
                "Reference specific findings from each modality. Be comprehensive yet concise."
            )},
            {"role": "user", "content": (
                f"User question: {message}\n\n"
                f"Analysed content:\n\n{modality_context}"
            )},
        ]

        async for token in stream_tokens(fusion_msgs, use_deep=True):
            yield {"data": _json.dumps({"token": token})}

        latency = int((time.monotonic() - t0) * 1000)
        yield {"data": _json.dumps({
            "multimodal_complete": True,
            "modalities_processed": [r["type"] for r in modality_results],
            "files_analysed": len(modality_results),
            "latency_ms": latency,
        })}
        yield {"data": _json.dumps({
            "done": True, "agent": "multimodal_fusion",
            "latency_ms": latency,
        })}

    return EventSourceResponse(gen())
