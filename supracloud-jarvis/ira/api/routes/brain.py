"""api/routes/brain.py — continuous realtime-brain WebSocket + lifecycle.

WS /ws/brain — stream the brain's private thoughts and suggested speech, and
feed it percepts. There is ONE persistent brain (single owner): it is created
and its tick loop is started in the app lifespan, so it survives across client
connections rather than being spun up per socket.

OFF BY DEFAULT. The brain calls the LLM continuously (reacting + idle
self-thought), so it must be explicitly opted into with IRA_BRAIN_ENABLED. When
disabled, the WebSocket accepts then closes with a clear message.

Protocol:
  Connect:  ws://host/ws/brain   (auth: Sec-WebSocket-Protocol: "bearer.<JWT>", or ?token=)
  Client →  {"type":"perceive","source":"user","text":"..."}   (source optional)
            {"action":"ping"}  →  {"action":"pong"}
  Server →  {"type":"thought","text":"..."}  |  {"type":"speak","text":"..."}
            {"type":"error","text":"..."}

Security: a client may NOT label a percept as a trusted source. Any client
supplied source is clamped to the external/untrusted set (never "internal"),
so all client input still flows through the brain's percept sanitization.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["brain"])
logger = logging.getLogger("ira.brain")

# Client-supplied percept sources are always external/untrusted. "internal"
# (IRA's own thought) and "timer" are reserved and never accepted from a client.
_CLIENT_SOURCES = {"user", "voice", "vision", "channel"}


def brain_enabled() -> bool:
    """Whether the continuous brain loop is opted in (default OFF)."""
    return os.getenv("IRA_BRAIN_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


def _safe_source(raw: object) -> str:
    """Clamp a client-supplied source to the untrusted external set."""
    s = str(raw or "user").strip().lower()
    return s if s in _CLIENT_SOURCES else "user"


async def feed_percept(app, source: str, text: str) -> bool:
    """Feed a percept to the running brain from another subsystem (voice, vision).

    The seam other IRA modules use to push perceptions in — e.g. an owner-gated
    voice transcript, or a vision caption. Returns True if delivered, False if the
    brain isn't running. The source is clamped to the untrusted external set and
    the call never raises, so callers can fire-and-forget safely.
    """
    brain = getattr(getattr(app, "state", None), "brain", None)
    if brain is None:
        return False
    text = (text or "").strip()
    if not text:
        return False
    try:
        await brain.perceive(_safe_source(source), text)
        return True
    except Exception as exc:  # noqa: BLE001 - never let a percept feed break a caller
        logger.debug("feed_percept failed (non-fatal): %s", exc)
        return False


# ── Lifecycle (called from main.lifespan) ────────────────────────────────────

async def start_brain(app) -> None:
    """Create the singleton brain and start its tick loop as a background task.

    No-op unless IRA_BRAIN_ENABLED. Failures are logged and swallowed so the
    brain can never block or crash API startup.
    """
    if not brain_enabled():
        logger.info("Realtime brain disabled (set IRA_BRAIN_ENABLED=true to enable)")
        return
    try:
        from agents.cortex_realtime_brain import (
            IraEmbedder, IraLLM, IraMemorySink, RealtimeBrain,
        )

        brain = RealtimeBrain(llm=IraLLM(), embedder=IraEmbedder(), memory=IraMemorySink())
        app.state.brain = brain
        task = asyncio.create_task(brain.run())
        task.add_done_callback(
            lambda t: t.cancelled() or (t.exception() and logger.warning(
                "Realtime brain loop ended: %s", t.exception()))
        )
        app.state.brain_task = task

        # Periodic long-term memory consolidation (set IRA_BRAIN_CONSOLIDATE_SECS=0 to disable).
        secs = float(os.getenv("IRA_BRAIN_CONSOLIDATE_SECS", "300"))
        if secs > 0:
            app.state.brain_consolidate_task = asyncio.create_task(
                _consolidation_loop(brain, secs))
        logger.info("Realtime brain online")
    except Exception as exc:  # noqa: BLE001 - never block startup
        logger.warning("Realtime brain failed to start (non-fatal): %s", exc)
        app.state.brain = None


async def _consolidation_loop(brain, secs: float) -> None:
    """Summarize recent working memory into long-term memory every `secs` seconds."""
    while True:
        await asyncio.sleep(secs)
        try:
            await brain.consolidate()
        except Exception as exc:  # noqa: BLE001 - never let consolidation crash the task
            logger.warning("Realtime brain consolidation failed: %s", exc)


async def stop_brain(app) -> None:
    """Stop the tick loop and cancel its task on shutdown."""
    brain = getattr(app.state, "brain", None)
    if brain is not None:
        brain.stop()
    for attr in ("brain_task", "brain_consolidate_task"):
        task = getattr(app.state, attr, None)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
            setattr(app.state, attr, None)
    app.state.brain = None


def _get_brain(websocket: WebSocket):
    return getattr(websocket.app.state, "brain", None)


# ── WebSocket stream ─────────────────────────────────────────────────────────

@router.websocket("/ws/brain")
async def ws_brain(websocket: WebSocket):
    # Auth mirrors /ws/notifications: prefer the bearer.<token> subprotocol
    # (keeps the JWT out of proxy logs); fall back to ?token= for dev clients.
    token: str | None = None
    selected_subprotocol: str | None = None
    for part in websocket.headers.get("sec-websocket-protocol", "").split(","):
        part = part.strip()
        if part.startswith("bearer."):
            token = part[len("bearer."):]
            selected_subprotocol = part
            break
    if not token:
        token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001)
        return

    from api.middleware.auth import decode_token  # lazy: keeps module import light

    try:
        decode_token(token)
    except Exception:
        await websocket.close(code=4001)
        return

    await websocket.accept(subprotocol=selected_subprotocol)

    brain = _get_brain(websocket)
    if brain is None:
        await websocket.send_text(json.dumps(
            {"type": "error", "text": "brain disabled (set IRA_BRAIN_ENABLED=true)"}))
        await websocket.close(code=1011)
        return

    async def _safe_send(payload: dict) -> None:
        try:
            await websocket.send_text(json.dumps(payload))
        except Exception:  # noqa: BLE001 - socket may be gone
            pass

    # Fire-and-forget so a slow/stuck client can never stall the shared brain.
    def _frame(kind: str):
        def cb(text: str):
            asyncio.create_task(_safe_send({"type": kind, "text": text}))
        return cb

    thought_cb = _frame("thought")
    speak_cb = _frame("speak")
    brain.on_thought(thought_cb)
    brain.on_speak(speak_cb)
    logger.info("Brain WebSocket client connected")

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except Exception:  # noqa: BLE001
                continue
            if msg.get("action") == "ping":
                await _safe_send({"action": "pong"})
                continue
            if msg.get("type") == "perceive":
                text = str(msg.get("text") or "").strip()
                if text:
                    await brain.perceive(_safe_source(msg.get("source")), text)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("Brain WebSocket session ended: %s", exc)
    finally:
        brain.off_thought(thought_cb)
        brain.off_speak(speak_cb)
        logger.info("Brain WebSocket client disconnected")
