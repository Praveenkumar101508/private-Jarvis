"""
Feature handler registry for chat_stream.  # Fix P24

Each handler exposes:
  matches(req) -> bool   — return True if this handler owns the request
  handle(req, user) -> EventSourceResponse  — execute and return the SSE response

Handlers are checked in order; the first match wins. Architect routing and the
main LLM event_generator remain in chat.py (tightly coupled to local state).
"""
from __future__ import annotations

import asyncio
import json
from typing import Protocol

from sse_starlette.sse import EventSourceResponse

from api.routes.chat import ChatRequest
from config import get_settings


class FeatureHandler(Protocol):
    def matches(self, req: "ChatRequest") -> bool: ...
    async def handle(self, req: "ChatRequest", user: str) -> "EventSourceResponse": ...


# ── Image Generation ──────────────────────────────────────────────────────────

class ImageGenHandler:
    def matches(self, req: ChatRequest) -> bool:
        if req.is_voice:
            return False
        from utils.search_tools import is_image_gen_request
        return is_image_gen_request(req.message)

    async def handle(self, req: ChatRequest, user: str) -> EventSourceResponse:
        async def _stream():
            yield {"data": json.dumps({"token": "Generating your image… "})}
            try:
                from api.routes.image_gen import GenerateRequest, _generate_sd_webui, _generate_replicate
                _cfg = get_settings()
                _url = _cfg.image_gen_url.rstrip("/")
                _tok = _cfg.replicate_api_token
                if _url or _tok:
                    gen_req = GenerateRequest(prompt=req.message, width=1024, height=1024, steps=20)
                    image_b64 = (
                        await _generate_sd_webui(gen_req, _url) if _url
                        else await _generate_replicate(gen_req, _tok, _cfg.flux_model)
                    )
                    yield {"data": json.dumps({
                        "image_generated": True, "image_b64": image_b64,
                        "mime_type": "image/png", "prompt": req.message,
                    })}
                    final_text = f"Here is your generated image based on: *{req.message}*"
                else:
                    final_text = (
                        "Image generation is not configured yet.\n\n"
                        "To enable it, add one of these to your `.env`:\n"
                        "- `IMAGE_GEN_URL=http://your-sd-webui:7860` (Stable Diffusion)\n"
                        "- `REPLICATE_API_TOKEN=r8_...` (Flux via Replicate)\n\n"
                        "Once configured, just ask me to *generate* or *draw* something and I will."
                    )
            except Exception as e:
                final_text = f"Image generation failed: {e}"
            for word in final_text.split(" "):
                yield {"data": json.dumps({"token": word + " "})}
                await asyncio.sleep(0.01)
            yield {"data": json.dumps({
                "done": True, "agent": "image_gen",
                "latency_ms": 0, "session_id": req.session_id,
            })}
        return EventSourceResponse(_stream())


# ── Image Edit ────────────────────────────────────────────────────────────────

class ImageEditHandler:
    def matches(self, req: ChatRequest) -> bool:
        if not req.image_b64:
            return False
        from utils.search_tools import is_image_edit_request
        return is_image_edit_request(req.message)

    async def handle(self, req: ChatRequest, user: str) -> EventSourceResponse:
        async def _stream():
            yield {"data": json.dumps({"token": "Editing your image… "})}
            try:
                from api.routes.image_gen import EditRequest, _edit_sd_webui, _edit_replicate
                _cfg = get_settings()
                _url = _cfg.image_gen_url.rstrip("/")
                _tok = _cfg.replicate_api_token
                if _url or _tok:
                    edit_req = EditRequest(image_b64=req.image_b64, instruction=req.message)
                    image_b64 = (
                        await _edit_sd_webui(edit_req, _url) if _url
                        else await _edit_replicate(edit_req, _tok)
                    )
                    yield {"data": json.dumps({
                        "image_generated": True, "image_b64": image_b64,
                        "mime_type": "image/png", "prompt": req.message,
                    })}
                    final_text = "Here is the edited image."
                else:
                    final_text = "Image editing requires IMAGE_GEN_URL or REPLICATE_API_TOKEN in .env."
            except Exception as e:
                final_text = f"Image editing failed: {e}"
            for word in final_text.split(" "):
                yield {"data": json.dumps({"token": word + " "})}
                await asyncio.sleep(0.01)
            yield {"data": json.dumps({
                "done": True, "agent": "image_edit",
                "latency_ms": 0, "session_id": req.session_id,
            })}
        return EventSourceResponse(_stream())


# ── Video Generation ──────────────────────────────────────────────────────────

class VideoGenHandler:
    def matches(self, req: ChatRequest) -> bool:
        if req.is_voice:
            return False
        from api.routes.video_gen import is_video_gen_request
        return is_video_gen_request(req.message)

    async def handle(self, req: ChatRequest, user: str) -> EventSourceResponse:
        from api.routes.video_gen import video_generate, VideoGenRequest
        return await video_generate(VideoGenRequest(prompt=req.message, session_id=req.session_id), user)


# ── Document Creation ─────────────────────────────────────────────────────────

class DocCreateHandler:
    def matches(self, req: ChatRequest) -> bool:
        if req.is_voice:
            return False
        from api.routes.document_create import is_doc_create_request
        return is_doc_create_request(req.message)

    async def handle(self, req: ChatRequest, user: str) -> EventSourceResponse:
        from api.routes.document_create import document_create, DocCreateRequest
        return await document_create(DocCreateRequest(prompt=req.message, session_id=req.session_id), user)


# ── Design Tools ──────────────────────────────────────────────────────────────

class DesignHandler:
    def matches(self, req: ChatRequest) -> bool:
        if req.is_voice:
            return False
        from api.routes.design_tools import is_design_request
        return is_design_request(req.message)

    async def handle(self, req: ChatRequest, user: str) -> EventSourceResponse:
        from api.routes.design_tools import design_generate, DesignRequest
        return await design_generate(DesignRequest(prompt=req.message, session_id=req.session_id), user)


# ── Audio Generation ──────────────────────────────────────────────────────────

class AudioGenHandler:
    def matches(self, req: ChatRequest) -> bool:
        if req.is_voice:
            return False
        from api.routes.audio_gen import is_audio_gen_request
        return is_audio_gen_request(req.message)

    async def handle(self, req: ChatRequest, user: str) -> EventSourceResponse:
        from api.routes.audio_gen import audio_generate, AudioGenRequest
        return await audio_generate(AudioGenRequest(prompt=req.message, session_id=req.session_id), user)


# ── Deep Research ─────────────────────────────────────────────────────────────

class DeepResearchHandler:
    def matches(self, req: ChatRequest) -> bool:
        if req.is_voice:
            return False
        from api.routes.deep_research import is_deep_research_request
        return is_deep_research_request(req.message)

    async def handle(self, req: ChatRequest, user: str) -> EventSourceResponse:
        from api.routes.deep_research import deep_research, DeepResearchRequest
        return await deep_research(DeepResearchRequest(topic=req.message, session_id=req.session_id), user)


# ── Article Generation ────────────────────────────────────────────────────────

class ArticleHandler:
    def matches(self, req: ChatRequest) -> bool:
        if req.is_voice:
            return False
        from api.routes.deep_research import is_article_request
        return is_article_request(req.message)

    async def handle(self, req: ChatRequest, user: str) -> EventSourceResponse:
        from api.routes.deep_research import generate_article, ArticleRequest
        return await generate_article(ArticleRequest(topic=req.message, session_id=req.session_id), user)


# ── Ordered registry — first match wins ──────────────────────────────────────
#
# Order matters: image_edit before image_gen (image_edit requires image_b64
# AND an edit keyword; image_gen is broader). video before doc/design/audio
# to avoid overlap.
HANDLER_REGISTRY: list[FeatureHandler] = [
    ImageEditHandler(),
    ImageGenHandler(),
    VideoGenHandler(),
    DocCreateHandler(),
    DesignHandler(),
    AudioGenHandler(),
    DeepResearchHandler(),
    ArticleHandler(),
]


async def dispatch(req: ChatRequest, user: str):
    """
    Iterate the handler registry; return the first matching handler's response,
    or None if no handler matches (caller falls through to main LLM stream).
    """
    for handler in HANDLER_REGISTRY:
        if handler.matches(req):
            return await handler.handle(req, user)
    return None
