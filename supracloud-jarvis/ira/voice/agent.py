"""
IRA Voice Agent — LiveKit Agents worker.

Architecture:
  User speaks → LiveKit room → IRA Voice Agent
    → Silero VAD (detect speech end)
    → Faster-Whisper STT (multilingual transcription + language detection)
    → IRA API (LangGraph multi-agent brain via HTTP)
    → Kokoro TTS (af_bella — warm, professional female voice)
    → LiveKit room → User hears IRA's response

This process runs as a standalone worker that connects to the LiveKit server
and waits for participants to join voice rooms. One agent instance is spawned
per active room.

Environment variables required:
  LIVEKIT_URL        — LiveKit server WebSocket URL
  LIVEKIT_API_KEY    — LiveKit API key
  LIVEKIT_API_SECRET — LiveKit API secret
  IRA_API_URL        — Internal URL to ira-api (e.g. http://ira-api:8000)
  IRA_API_TOKEN      — JWT token for ira-api authentication
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import AsyncIterator

import httpx
from livekit import rtc
from livekit.agents import (
    AgentSession,
    JobContext,
    RoomInputOptions,
    WorkerOptions,
    cli,
    llm,
)
from livekit.plugins import silero

from voice.stt import IRAFasterWhisperSTT
from voice.tts import IRAKokoroTTS
from voice.language import get_greeting, normalise_lang, LANGUAGE_NAMES

logger = logging.getLogger("ira.voice")

# ── Biometric pipeline startup check ─────────────────────────────────────────
try:
    from voice.biometrics import is_owner_authenticated  # noqa: F401
    logger.info("Biometric pipeline: ACTIVE — ECAPA-TDNN speaker verification ready")
except ImportError as _bio_err:
    logger.warning(f"Biometric pipeline: DISABLED — {_bio_err}")

# ── Configuration ─────────────────────────────────────────────────────────────
IRA_API_URL = os.getenv("IRA_API_URL", "http://ira-api:8000")
IRA_API_TOKEN = os.getenv("IRA_API_TOKEN", "")

# Whisper model size — trade-off between accuracy and latency
# large-v3: best accuracy (production recommended)
# small    : fastest (~0.3-0.5s) — use on Shadow PC / low-memory hosts
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large-v3")

# Fix #123: Kokoro voice loaded from IRA_VOICE env var (set in .env.example).
# Allows switching voice without rebuilding the image — "af_bella" (warm) or
# "af_heart" (softer). Falls back to af_bella if the env var is not set.
IRA_VOICE = os.getenv("IRA_VOICE", "af_bella")

# Maximum duration for a single voice session (#32).
# Guards against abandoned sessions keeping the worker alive indefinitely.
MAX_SESSION_SECONDS: float = 4 * 3600  # 4 hours


# ── IRA LLM Adapter ───────────────────────────────────────────────────────────

class IRALLMAdapter(llm.LLM):
    """
    Bridges LiveKit Agents' LLM interface to IRA's FastAPI + LangGraph backend.
    Each chat() call sends the user's message to /api/v1/chat and streams back
    the response token-by-token via SSE.
    """

    def __init__(self, session_id: str):
        super().__init__()
        self._session_id = session_id
        self._http = httpx.AsyncClient(
            base_url=IRA_API_URL,
            headers={"Authorization": f"Bearer {IRA_API_TOKEN}"},
            timeout=httpx.Timeout(connect=5, read=120, write=30, pool=5),
        )
        # Stores the raw PCM bytes of the latest user utterance for biometric verification
        self._pending_audio: bytes = b""

    def set_audio_bytes(self, audio: bytes) -> None:
        """Called by the speech-committed handler before chat() is invoked."""
        self._pending_audio = audio

    def chat(
        self,
        *,
        chat_ctx: llm.ChatContext,
        conn_options: llm.LLMOptions | None = None,
    ) -> "IRALLMStream":
        # Extract the latest user message from LiveKit's chat context
        user_msg = ""
        for msg in reversed(chat_ctx.messages):
            if msg.role == llm.ChatRole.USER:
                user_msg = str(msg.content) if msg.content else ""
                break
        # Pass the buffered audio so the biometric gate inside _run() can verify
        audio = self._pending_audio
        self._pending_audio = b""  # reset after each turn
        return IRALLMStream(
            llm=self,
            session_id=self._session_id,
            user_message=user_msg,
            http=self._http,
            is_owner=False,
            audio_bytes=audio,
        )

    async def aclose(self):
        await self._http.aclose()


class IRALLMStream(llm.LLMStream):
    """Streams IRA's response back to the voice pipeline token-by-token."""

    def __init__(
        self,
        llm: IRALLMAdapter,
        session_id: str,
        user_message: str,
        http: httpx.AsyncClient,
        is_owner: bool = False,
        audio_bytes: bytes = b"",
    ):
        super().__init__(llm=llm, chat_ctx=llm.ChatContext(), tools=[])
        self._session_id = session_id
        self._user_message = user_message
        self._http = http
        self._is_owner = is_owner
        self._audio_bytes = audio_bytes

    async def _run(self) -> None:
        if not self._user_message.strip():
            return

        # Run biometric verification against the audio that produced this transcript
        owner_verified = self._is_owner
        if not owner_verified and self._audio_bytes:
            try:
                from voice.biometrics import is_owner_authenticated
                owner_verified = await is_owner_authenticated(self._audio_bytes, session_id=self._session_id)
            except Exception as e:
                logger.warning(f"Biometric check failed gracefully: {e}")
                owner_verified = False

        try:
            async with self._http.stream(
                "POST",
                "/api/v1/chat/stream",
                json={
                    "message": self._user_message,
                    "session_id": self._session_id,
                    "stream": True,
                    "is_voice_owner": owner_verified,
                    "is_voice": True,  # Enforces concise 1-2 sentence voice replies
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
                        import json
                        data = json.loads(payload)
                        if "token" in data:
                            self._event_ch.send_nowait(
                                llm.ChatChunk(
                                    choices=[
                                        llm.Choice(
                                            delta=llm.ChoiceDelta(
                                                role=llm.ChatRole.ASSISTANT,
                                                content=data["token"],
                                            )
                                        )
                                    ]
                                )
                            )
                        elif data.get("done"):
                            break
                    except Exception:
                        continue
        except Exception as e:
            logger.error(f"IRA API stream error: {e}")
            # Graceful fallback: short error response
            self._event_ch.send_nowait(
                llm.ChatChunk(
                    choices=[
                        llm.Choice(
                            delta=llm.ChoiceDelta(
                                role=llm.ChatRole.ASSISTANT,
                                content="I'm sorry, I encountered a brief issue. Please try again.",
                            )
                        )
                    ]
                )
            )


# ── Agent entrypoint ──────────────────────────────────────────────────────────

async def entrypoint(ctx: JobContext) -> None:
    """
    Called by the LiveKit worker when a participant joins a room.
    Sets up IRA's full voice pipeline for that room.
    """
    logger.info(f"IRA voice agent starting for room: {ctx.room.name}")

    await ctx.connect()

    # Unique session per voice room — links to IRA's memory system
    session_id = f"voice_{ctx.room.name}_{uuid.uuid4().hex[:8]}"

    # Initialise components
    stt = IRAFasterWhisperSTT(model_size=WHISPER_MODEL, device="cpu", compute_type="int8")
    tts_engine = IRAKokoroTTS(voice=IRA_VOICE, speed=1.05)  # Fix #123: voice from env
    vad = silero.VAD.load(
        min_silence_duration=0.3,   # 300ms — slightly longer pause before cutting off
        min_speech_duration=0.1,    # 100ms — catches "wait", "stop", single words
        activation_threshold=0.5,   # Standard sensitivity — reduces false triggers
        max_buffered_speech=60.0,   # Allow up to 60s utterances
    )
    ira_llm = IRALLMAdapter(session_id=session_id)

    session = AgentSession(
        stt=stt,
        llm=ira_llm,
        tts=tts_engine,
        vad=vad,
        turn_detection=None,  # VAD handles turn detection
    )

    # Greet the user when they join
    await session.say(
        get_greeting("en"),  # IRA's intro — language switches after first user utterance
        allow_interruptions=True,
    )

    # Subscribe to audio from the first participant (or wait for one to join)
    participant = await _wait_for_participant(ctx)
    if participant is None:
        logger.warning("No participant joined within timeout. Agent exiting.")
        return

    logger.info(f"IRA is listening to participant: {participant.identity}")

    @session.on("user_speech_committed")
    def on_user_speech(event):
        # Capture per-utterance audio for biometric verification
        # livekit-agents 0.11.x surfaces audio bytes in the speech_committed event
        if hasattr(event, "audio") and event.audio:
            try:
                ira_llm.set_audio_bytes(bytes(event.audio))
            except Exception as e:
                logger.debug(f"Biometric audio capture skipped: {e}")

        # Language detection from committed speech event
        detected = getattr(event, "language", "en") or "en"
        lang = normalise_lang(detected)
        if lang != "en":
            lang_name = LANGUAGE_NAMES.get(lang, lang)
            logger.info(f"Language switched to: {lang_name} ({lang})")

    await session.start(
        ctx.room,
        participant=participant,
        room_input_options=RoomInputOptions(
            # Subscribe to microphone audio only (not video)
            audio_enabled=True,
            video_enabled=False,
        ),
    )

    logger.info(f"IRA voice session active for {participant.identity}")

    # Keep the agent alive until the participant disconnects — but cap at
    # MAX_SESSION_SECONDS to prevent zombie sessions if the disconnect event is
    # never delivered (e.g., hard network drop, container restart). (#32)
    try:
        await asyncio.wait_for(ctx.wait_for_disconnect(), timeout=MAX_SESSION_SECONDS)
        logger.info("Participant disconnected. IRA voice session ending.")
    except asyncio.TimeoutError:
        logger.warning(
            f"Voice session for {participant.identity} reached the "
            f"{MAX_SESSION_SECONDS / 3600:.0f}h maximum duration. Ending automatically."
        )
    await ira_llm.aclose()


async def _wait_for_participant(ctx: JobContext, timeout: float = 30.0):
    """Wait for a real (non-agent) participant to join the room."""
    participants = [
        p for p in ctx.room.remote_participants.values()
        if not p.identity.startswith("ira-")
    ]
    if participants:
        return participants[0]

    # Wait for someone to join
    future: asyncio.Future = asyncio.get_running_loop().create_future()

    def on_participant_connected(participant: rtc.RemoteParticipant):
        if not participant.identity.startswith("ira-") and not future.done():
            future.set_result(participant)

    ctx.room.on("participant_connected", on_participant_connected)
    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        return None


# ── Worker entry point ────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            # Worker connects to LiveKit and waits for room events
        )
    )
