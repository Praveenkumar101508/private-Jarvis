"""
TTS (Text-to-Speech) abstraction layer — ElevenLabs, Azure, Google
IRA uses a warm Indian female voice by default
"""
import structlog

from config import settings

log = structlog.get_logger()


async def synthesize(text: str, language: str = "en") -> bytes:
    provider = settings.tts_provider
    if provider == "elevenlabs":
        return await _elevenlabs_synthesize(text)
    elif provider == "azure":
        return await _azure_synthesize(text, language)
    else:
        return await _elevenlabs_synthesize(text)


async def _elevenlabs_synthesize(text: str) -> bytes:
    from elevenlabs.client import AsyncElevenLabs
    client = AsyncElevenLabs(api_key=settings.elevenlabs_api_key)
    audio = await client.generate(
        text=text,
        voice=settings.elevenlabs_voice_id,
        model="eleven_turbo_v2_5",
    )
    chunks = []
    async for chunk in audio:
        chunks.append(chunk)
    return b"".join(chunks)


async def _azure_synthesize(text: str, language: str) -> bytes:
    import azure.cognitiveservices.speech as speechsdk

    voice = settings.azure_tts_voice
    if language == "hi":
        voice = "hi-IN-SwaraNeural"
    elif language == "te":
        voice = "te-IN-ShrutiNeural"
    elif language == "ta":
        voice = "ta-IN-PallaviNeural"

    config = speechsdk.SpeechConfig(
        subscription=settings.azure_tts_key,
        region=settings.azure_tts_region,
    )
    config.speech_synthesis_voice_name = voice

    synthesizer = speechsdk.SpeechSynthesizer(speech_config=config, audio_config=None)
    result = synthesizer.speak_text_async(text).get()

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        return result.audio_data
    raise RuntimeError(f"Azure TTS failed: {result.cancellation_details}")
