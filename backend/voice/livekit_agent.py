"""
Phase 3: LiveKit Voice Agent — IRA's voice presence
Runs as a standalone worker process
"""
import asyncio
import logging

from livekit.agents import (
    AutoSubscribe,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
    llm,
)
from livekit.agents.voice_assistant import VoiceAssistant
from livekit.plugins import deepgram, elevenlabs, openai, silero

from config import settings
from persona.ira import get_system_prompt

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ira.voice")


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    log.info("IRA voice agent starting", room=ctx.room.name)

    initial_ctx = llm.ChatContext().append(
        role="system",
        text=get_system_prompt("voice"),
    )

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # Build STT
    if settings.stt_provider == "deepgram":
        stt = deepgram.STT(api_key=settings.deepgram_api_key)
    else:
        stt = openai.STT(api_key=settings.openai_api_key)

    # Build TTS
    if settings.tts_provider == "elevenlabs":
        tts = elevenlabs.TTS(
            api_key=settings.elevenlabs_api_key,
            voice_id=settings.elevenlabs_voice_id,
            model_id="eleven_turbo_v2_5",
        )
    else:
        tts = openai.TTS(api_key=settings.openai_api_key, voice="nova")

    # Build LLM
    if settings.llm_provider == "anthropic":
        from livekit.plugins import anthropic
        agent_llm = anthropic.LLM(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
        )
    else:
        agent_llm = openai.LLM(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
        )

    assistant = VoiceAssistant(
        vad=ctx.proc.userdata["vad"],
        stt=stt,
        llm=agent_llm,
        tts=tts,
        chat_ctx=initial_ctx,
    )

    assistant.start(ctx.room)

    await asyncio.sleep(1)
    await assistant.say(
        "Namaste! I'm IRA, your intelligent assistant. How may I help you today?",
        allow_interruptions=True,
    )

    log.info("IRA voice agent ready")
    await asyncio.Event().wait()


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
        )
    )
