"""Faster-Whisper STT — livekit-agents 1.5.x compatible."""
from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import numpy as np
from faster_whisper import WhisperModel
from livekit.agents import stt
from livekit.agents.stt import SpeechData, SpeechEvent, SpeechEventType, STTCapabilities
from livekit.agents.types import NOT_GIVEN, APIConnectOptions, NotGivenOr
from livekit.agents.utils import AudioBuffer

from voice.language import normalise_lang

logger = logging.getLogger("ira.stt")

_STT_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="whisper")

LIVEKIT_SAMPLE_RATE = 48_000
WHISPER_SAMPLE_RATE = 16_000
DOWNSAMPLE_RATIO = LIVEKIT_SAMPLE_RATE // WHISPER_SAMPLE_RATE  # 3


@lru_cache(maxsize=1)
def _load_model(model_size: str, device: str, compute_type: str) -> WhisperModel:
    logger.info(f"Loading Whisper {model_size} on {device} ({compute_type})...")
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    logger.info("Whisper ready.")
    return model


def _downsample(audio_bytes: bytes) -> np.ndarray:
    pcm = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    return pcm[::DOWNSAMPLE_RATIO]


def _transcribe_sync(audio: np.ndarray, model: WhisperModel, language: str | None) -> tuple[str, str, float]:
    segments, info = model.transcribe(
        audio,
        language=language,
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300},
        word_timestamps=False,
    )
    transcript = " ".join(seg.text.strip() for seg in segments).strip()
    detected_lang = normalise_lang(info.language)
    return transcript, detected_lang, float(info.language_probability)


class IRAFasterWhisperSTT(stt.STT):
    def __init__(
        self,
        model_size: str = "small",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str | None = None,
    ):
        super().__init__(
            capabilities=STTCapabilities(
                streaming=False,
                interim_results=False,
                offline_recognize=True,
            )
        )
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._language = language

    def _get_model(self) -> WhisperModel:
        return _load_model(self._model_size, self._device, self._compute_type)

    async def _recognize_impl(
        self,
        buffer: AudioBuffer,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions,
    ) -> SpeechEvent:
        t0 = time.monotonic()

        audio_bytes = b"".join(frame.data for frame in buffer)
        audio_array = _downsample(audio_bytes)

        if len(audio_array) < 1600:
            return SpeechEvent(
                type=SpeechEventType.FINAL_TRANSCRIPT,
                alternatives=[SpeechData(text="", language="en", confidence=0.0)],
            )

        model = self._get_model()
        lang_hint = (language if language is not NOT_GIVEN else None) or self._language

        loop = asyncio.get_running_loop()
        transcript, detected_lang, confidence = await loop.run_in_executor(
            _STT_EXECUTOR, _transcribe_sync, audio_array, model, lang_hint
        )

        latency_ms = int((time.monotonic() - t0) * 1000)
        logger.info(f"STT: lang={detected_lang} conf={confidence:.2f} latency={latency_ms}ms | {transcript[:60]}")

        return SpeechEvent(
            type=SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[SpeechData(text=transcript, language=detected_lang, confidence=confidence)],
        )
