"""
STT (Speech-to-Text) abstraction layer — supports Deepgram, Whisper, Google
"""
import io
import structlog

from config import settings

log = structlog.get_logger()


async def transcribe(audio_bytes: bytes, language: str = "en") -> str:
    provider = settings.stt_provider
    if provider == "deepgram":
        return await _deepgram_transcribe(audio_bytes, language)
    elif provider == "whisper":
        return await _whisper_transcribe(audio_bytes, language)
    else:
        return await _deepgram_transcribe(audio_bytes, language)


async def _deepgram_transcribe(audio_bytes: bytes, language: str) -> str:
    from deepgram import DeepgramClient, PrerecordedOptions
    client = DeepgramClient(settings.deepgram_api_key)
    options = PrerecordedOptions(
        model="nova-2",
        language=language,
        smart_format=True,
        punctuate=True,
    )
    response = await client.listen.asyncprerecorded.v("1").transcribe_file(
        {"buffer": audio_bytes}, options
    )
    return response["results"]["channels"][0]["alternatives"][0]["transcript"]


async def _whisper_transcribe(audio_bytes: bytes, language: str) -> str:
    import openai as oai
    client = oai.AsyncOpenAI(api_key=settings.openai_api_key)
    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = "audio.webm"
    transcript = await client.audio.transcriptions.create(
        model="whisper-1",
        file=audio_file,
        language=language if language != "en" else None,
    )
    return transcript.text
