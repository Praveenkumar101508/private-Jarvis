"""
IRA Voice Agent — LiveKit Agents 1.x worker.

  User speaks → LiveKit room → Silero VAD → Faster-Whisper STT (1.x)
    → IRA LLM adapter (HTTP to ira-api /chat/stream, the IRA brain)
    → Kokoro TTS (1.x) → LiveKit room → user hears IRA

Rewritten for LiveKit Agents 1.x:
  * AgentSession + Agent + RoomInputOptions (no 0.x ctx plumbing).
  * The LLM adapter subclasses llm.LLM and emits 1.x ChatChunk(delta=ChoiceDelta);
    the 0.x llm.Choice / ChatRole / multi-choice API is gone.
  * Bug fix: the IRALLMStream constructor parameter named `llm` shadowed the imported
    `llm` module (guaranteed AttributeError on llm.ChatContext()); renamed to `adapter`.

NOTE: this targets the LiveKit Agents 1.x API and is validated on the Shadow box
(no GPU/audio here). Per-utterance biometric audio is read from the STT plugin's
last_utterance_pcm16 stash.

Env: LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET, IRA_API_URL, IRA_API_TOKEN.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid

import httpx
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    RoomInputOptions,
    WorkerOptions,
    cli,
    llm,
    utils,
)
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS
from livekit.plugins import silero

from voice.gate import gate_from_audio
from voice.language import get_greeting
from voice.stt import IRAFasterWhisperSTT
from voice.tts import IRAKokoroTTS

logger = logging.getLogger("ira.voice")

try:
    from voice.biometrics import is_owner_authenticated  # noqa: F401
    logger.info("Biometric pipeline: ACTIVE — ECAPA-TDNN speaker verification ready")
except ImportError as _bio_err:
    logger.warning(f"Biometric pipeline: DISABLED — {_bio_err}")


def _get_voice_config() -> dict:
    return {
        "api_url": os.getenv("IRA_API_URL", "http://ira-api:8000"),
        "api_token": os.getenv("IRA_API_TOKEN", ""),
        "whisper_model": os.getenv("WHISPER_MODEL", "large-v3"),
        "voice": os.getenv("IRA_VOICE", "af_bella"),
        "max_session_seconds": float(os.getenv("MAX_SESSION_SECONDS", str(4 * 3600))),
    }


def _last_user_text(chat_ctx) -> str:
    """Extract the latest user message text from a 1.x ChatContext (defensively)."""
    for item in reversed(getattr(chat_ctx, "items", []) or []):
        if getattr(item, "role", None) != "user":
            continue
        text = getattr(item, "text_content", None)
        if text:
            return text
        content = getattr(item, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return " ".join(str(p) for p in content if isinstance(p, str))
    return ""


# ── IRA LLM Adapter (1.x) ─────────────────────────────────────────────────────

class IRALLMAdapter(llm.LLM):
    """Bridges LiveKit Agents' LLM interface to IRA's brain (HTTP /chat/stream)."""

    def __init__(self, session_id: str, stt: IRAFasterWhisperSTT):
        super().__init__()
        self._session_id = session_id
        self._stt = stt          # read per-utterance audio for the biometric gate
        cfg = _get_voice_config()
        self._http = httpx.AsyncClient(
            base_url=cfg["api_url"],
            headers={"Authorization": f"Bearer {cfg['api_token']}"},
            timeout=httpx.Timeout(connect=5, read=120, write=30, pool=5),
        )

    def chat(self, *, chat_ctx, tools=None, conn_options=DEFAULT_API_CONNECT_OPTIONS, **kwargs):
        user_msg = _last_user_text(chat_ctx)
        audio = self._stt.last_utterance_pcm16          # the utterance that produced it
        self._stt.last_utterance_pcm16 = b""            # consume
        return IRALLMStream(
            adapter=self,                                # NOTE: not `llm` — that shadows the module
            chat_ctx=chat_ctx,
            tools=tools or [],
            conn_options=conn_options,
            session_id=self._session_id,
            user_message=user_msg,
            http=self._http,
            audio_bytes=audio,
        )

    async def aclose(self):
        await self._http.aclose()


class IRALLMStream(llm.LLMStream):
    """Streams IRA's response back to the voice pipeline as 1.x ChatChunks."""

    def __init__(self, *, adapter, chat_ctx, tools, conn_options,
                 session_id, user_message, http, audio_bytes=b""):
        super().__init__(adapter, chat_ctx=chat_ctx, tools=tools, conn_options=conn_options)
        self._session_id = session_id
        self._user_message = user_message
        self._http = http
        self._audio_bytes = audio_bytes

    def _emit(self, content: str) -> None:
        self._event_ch.send_nowait(
            llm.ChatChunk(id=utils.shortuuid(),
                          delta=llm.ChoiceDelta(role="assistant", content=content))
        )

    async def _run(self) -> None:
        if not self._user_message.strip():
            return

        # 4.4: biometric owner-gate (fail-closed) on the audio that produced this turn.
        decision = await gate_from_audio(self._audio_bytes, session_id=self._session_id)
        is_owner = decision["is_owner"]

        try:
            async with self._http.stream(
                "POST", "/api/v1/chat/stream",
                json={
                    "message": self._user_message,
                    "session_id": self._session_id,
                    "stream": True,
                    "is_voice_owner": is_owner,   # feeds IRA's server-side owner gate
                    "is_voice": True,             # concise 1–2 sentence voice replies
                },
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload:
                        continue
                    try:
                        data = json.loads(payload)
                    except Exception:
                        continue
                    if data.get("token"):
                        self._emit(data["token"])
                    elif data.get("done"):
                        break
        except Exception as e:  # noqa: BLE001 — graceful spoken fallback
            logger.error(f"IRA API stream error: {e}")
            self._emit("I'm sorry, I encountered a brief issue. Please try again.")


# ── IRA agent + entrypoint (1.x) ──────────────────────────────────────────────

class IRAVoiceAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=(
                "You are IRA, a warm, professional assistant. The brain is IRA's own "
                "backend; keep spoken replies to one or two sentences."
            )
        )


async def entrypoint(ctx: JobContext) -> None:
    logger.info(f"IRA voice agent starting for room: {ctx.room.name}")
    await ctx.connect()

    session_id = f"voice_{ctx.room.name}_{uuid.uuid4().hex[:8]}"
    cfg = _get_voice_config()

    stt = IRAFasterWhisperSTT(model_size=cfg["whisper_model"], device="cpu", compute_type="int8")
    tts_engine = IRAKokoroTTS(voice=cfg["voice"], speed=1.05)
    vad = silero.VAD.load(min_silence_duration=0.3, min_speech_duration=0.1)
    adapter = IRALLMAdapter(session_id=session_id, stt=stt)

    session = AgentSession(stt=stt, llm=adapter, tts=tts_engine, vad=vad)

    await session.start(
        agent=IRAVoiceAgent(),
        room=ctx.room,
        room_input_options=RoomInputOptions(),
    )

    # Greet once the session is live; language switches after the first utterance.
    await session.say(get_greeting("en"), allow_interruptions=True)

    # Keep the session alive until the room disconnects, capped to avoid zombies.
    done = asyncio.Event()
    ctx.room.on("disconnected", lambda *_: done.set())
    try:
        await asyncio.wait_for(done.wait(), timeout=cfg["max_session_seconds"])
        logger.info("Room disconnected. IRA voice session ending.")
    except asyncio.TimeoutError:
        logger.warning("Voice session hit the max duration. Ending automatically.")
    finally:
        await adapter.aclose()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
