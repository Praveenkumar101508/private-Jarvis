"""
LiveKit Voice Agent — IRA's voice presence.
Runs as a standalone worker process.

Provider selection via STT_PROVIDER / TTS_PROVIDER / LLM_PROVIDER env vars:
  STT_PROVIDER=faster_whisper  → 100% local, no cloud dependency (sovereign mode)
  STT_PROVIDER=deepgram        → cloud Deepgram
  TTS_PROVIDER=kokoro          → 100% local kokoro ONNX (sovereign mode)
  TTS_PROVIDER=elevenlabs      → cloud ElevenLabs
  LLM_PROVIDER=ollama          → local Ollama (llama3.1:8b router)
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
from livekit.plugins import silero

from config import settings
from persona.ira import get_system_prompt

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ira.voice")


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


def _build_stt():
    if settings.stt_provider == "faster_whisper":
        from voice.local_stt import LocalSTT, LocalSTTOptions
        log.info("STT: faster-whisper (local)", model=settings.whisper_model)
        return LocalSTT(LocalSTTOptions(
            model_size=settings.whisper_model,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
        ))
    if settings.stt_provider == "deepgram":
        from livekit.plugins import deepgram
        return deepgram.STT(api_key=settings.deepgram_api_key)
    from livekit.plugins import openai as lk_openai
    return lk_openai.STT(api_key=settings.openai_api_key)


def _build_tts():
    if settings.tts_provider == "kokoro":
        from voice.local_tts import LocalTTS
        log.info("TTS: kokoro ONNX (local)", voice=settings.kokoro_voice)
        return LocalTTS(
            model_path=settings.kokoro_model_path,
            voices_path=settings.kokoro_voices_path,
            voice=settings.kokoro_voice,
            speed=settings.kokoro_speed,
        )
    if settings.tts_provider == "elevenlabs":
        from livekit.plugins import elevenlabs
        return elevenlabs.TTS(
            api_key=settings.elevenlabs_api_key,
            voice_id=settings.elevenlabs_voice_id,
            model_id="eleven_turbo_v2_5",
        )
    from livekit.plugins import openai as lk_openai
    return lk_openai.TTS(api_key=settings.openai_api_key, voice="nova")


def _build_llm():
    if settings.llm_provider == "ollama":
        from livekit.plugins import openai as lk_openai
        log.info("LLM: Ollama (local)", model=settings.ollama_fast_model)
        return lk_openai.LLM.with_ollama(
            model=settings.ollama_fast_model,
            base_url=settings.ollama_base_url,
        )
    if settings.llm_provider == "anthropic":
        from livekit.plugins import anthropic
        return anthropic.LLM(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
        )
    from livekit.plugins import openai as lk_openai
    return lk_openai.LLM(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
    )


async def entrypoint(ctx: JobContext):
    log.info("IRA voice agent starting", room=ctx.room.name)

    initial_ctx = llm.ChatContext().append(
        role="system",
        text=get_system_prompt("voice"),
    )

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    assistant = VoiceAssistant(
        vad=ctx.proc.userdata["vad"],
        stt=_build_stt(),
        llm=_build_llm(),
        tts=_build_tts(),
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
