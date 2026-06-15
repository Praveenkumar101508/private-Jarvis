"""IRA Voice Agent — LiveKit Agents 1.5.x"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid as _uuid

import httpx
from dotenv import load_dotenv

# Load .env from ira/ directory (parent of voice/)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli, llm
from livekit.agents.llm import ChatChunk, ChoiceDelta
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions, NOT_GIVEN, NotGivenOr
from livekit.plugins import silero

from voice.stt import IRAFasterWhisperSTT
from voice.tts import IRAKokoroTTS
from voice.language import get_greeting

logger = logging.getLogger("ira.voice")

IRA_API_URL   = os.getenv("IRA_API_URL",   "http://localhost:8000")
IRA_API_TOKEN = os.getenv("IRA_VOICE_API_TOKEN", os.getenv("IRA_API_TOKEN", ""))
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")


class IRALLMAdapter(llm.LLM):
    """Bridges LiveKit's LLM interface to IRA's /api/v1/chat/stream endpoint."""

    def __init__(self, session_id: str):
        super().__init__()
        self._session_id = session_id
        self._http = httpx.AsyncClient(
            base_url=IRA_API_URL,
            headers={"Authorization": f"Bearer {IRA_API_TOKEN}"},
            timeout=httpx.Timeout(connect=5, read=120, write=30, pool=5),
        )

    def chat(
        self,
        *,
        chat_ctx: llm.ChatContext,
        tools=None,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
        parallel_tool_calls: NotGivenOr[bool] = NOT_GIVEN,
        tool_choice=NOT_GIVEN,
        extra_kwargs=NOT_GIVEN,
    ) -> "IRALLMStream":
        # Extract the latest user message — content is list[ChatContent], use text_content
        user_msg = ""
        for msg in reversed(chat_ctx.messages()):
            if msg.role == "user":
                user_msg = msg.text_content or ""
                break

        return IRALLMStream(
            llm_instance=self,
            chat_ctx=chat_ctx,
            conn_options=conn_options,
            session_id=self._session_id,
            user_message=user_msg,
            http=self._http,
        )

    async def aclose(self) -> None:
        await self._http.aclose()


class IRALLMStream(llm.LLMStream):
    def __init__(self, *, llm_instance, chat_ctx, conn_options, session_id, user_message, http):
        super().__init__(
            llm=llm_instance,
            chat_ctx=chat_ctx,
            tools=[],
            conn_options=conn_options,
        )
        self._session_id = session_id
        self._user_message = user_message
        self._http = http

    async def _run(self) -> None:
        if not self._user_message.strip():
            return
        try:
            async with self._http.stream(
                "POST",
                "/api/v1/chat/stream",
                json={
                    "message": self._user_message,
                    "session_id": self._session_id,
                    "stream": True,
                    "is_voice_owner": False,
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
                        if "token" in data:
                            self._event_ch.send_nowait(
                                ChatChunk(
                                    id=_uuid.uuid4().hex,
                                    delta=ChoiceDelta(role="assistant", content=data["token"]),
                                )
                            )
                        elif data.get("done"):
                            break
                    except Exception:
                        continue
        except Exception as e:
            logger.error(f"IRA API stream error: {e}")
            self._event_ch.send_nowait(
                ChatChunk(
                    id=_uuid.uuid4().hex,
                    delta=ChoiceDelta(role="assistant", content="Sorry, I had a brief issue. Please try again."),
                )
            )


async def entrypoint(ctx: JobContext) -> None:
    logger.info(f"IRA voice agent starting: {ctx.room.name}")
    await ctx.connect()

    session_id = f"voice_{ctx.room.name}_{_uuid.uuid4().hex[:8]}"
    ira_llm = IRALLMAdapter(session_id=session_id)

    session = AgentSession(
        vad=silero.VAD.load(
            min_silence_duration=0.4,
            min_speech_duration=0.15,
            activation_threshold=0.5,
        ),
        stt=IRAFasterWhisperSTT(
            model_size=WHISPER_MODEL,
            device="cpu",
            compute_type="int8",
        ),
        llm=ira_llm,
        tts=IRAKokoroTTS(voice="af_bella", speed=1.05),
    )

    await session.start(
        room=ctx.room,
        agent=Agent(
            instructions=(
                "You are IRA, a private AI assistant. "
                "Keep ALL voice replies under 2 sentences. Be direct and concise. "
                "Never list items. Speak like a human, not a document."
            )
        ),
    )

    await session.say(get_greeting("en"), allow_interruptions=True)
    logger.info("IRA is listening.")
    await ctx.wait_for_disconnect()
    await ira_llm.aclose()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    # "spawn" avoids AF_UNIX forkserver sockets which fail on /mnt/c/ (Windows NTFS)
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            multiprocessing_context="spawn",
        )
    )
