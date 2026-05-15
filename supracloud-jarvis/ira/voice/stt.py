"""
Faster-Whisper STT plugin for LiveKit Agents.

Model: large-v3 (best accuracy for Indian + European languages)
Device: CPU (preserves all 20GB VRAM for LLM inference)
Language: auto-detect on every utterance

Performance on CPU (RTX A4500 host, 16+ CPU cores expected):
  Short utterances (<5s) : ~0.8–1.5s transcription latency
  Long utterances (<30s) : ~3–5s transcription latency

For lower latency on short queries, swap large-v3 for 'medium' or 'small'.
"""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import AsyncIterator

import numpy as np
from faster_whisper import WhisperModel
from livekit.agents import stt, utils
from livekit.agents.stt import SpeechData, SpeechEvent, SpeechEventType

from voice.language import normalise_lang

logger = logging.getLogger("ira.stt")

_STT_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="whisper")

# Audio constants — LiveKit sends 48kHz, Whisper expects 16kHz
LIVEKIT_SAMPLE_RATE = 48_000
WHISPER_SAMPLE_RATE = 16_000
DOWNSAMPLE_RATIO = LIVEKIT_SAMPLE_RATE // WHISPER_SAMPLE_RATE  # = 3


@lru_cache(maxsize=1)
def _load_model(model_size: str, device: str, compute_type: str) -> WhisperModel:
    logger.info(f"Loading Whisper {model_size} on {device} ({compute_type})...")
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    logger.info("Whisper model loaded.")
    return model


def _downsample(audio_bytes: bytes) -> np.ndarray:
    """Convert 48kHz int16 PCM bytes to 16kHz float32 array for Whisper."""
    pcm = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    # Simple decimation (ratio=3): take every Nth sample
    return pcm[::DOWNSAMPLE_RATIO]


def _transcribe_sync(
    audio: np.ndarray,
    model: WhisperModel,
    language: str | None,
) -> tuple[str, str, float]:
    """
    Run Whisper transcription synchronously (called from thread pool).
    Returns: (transcript, detected_lang, confidence)
    """
    segments, info = model.transcribe(
        audio,
        language=language,           # None = auto-detect
        beam_size=5,
        vad_filter=True,             # Skip silent segments
        vad_parameters={"min_silence_duration_ms": 300},
        word_timestamps=False,
    )
    transcript = " ".join(seg.text.strip() for seg in segments).strip()
    detected_lang = normalise_lang(info.language)
    confidence = float(info.language_probability)
    return transcript, detected_lang, confidence


class IRAFasterWhisperSTT(stt.STT):
    """
    LiveKit-compatible STT plugin backed by Faster-Whisper.
    Handles multilingual audio with automatic language detection.
    """

    def __init__(
        self,
        model_size: str = "large-v3",
        device: str = "cpu",
        # int8 is fastest on CPU with acceptable accuracy loss
        compute_type: str = "int8",
        language: str | None = None,  # None = auto-detect
    ):
        super().__init__(
            capabilities=stt.STTCapabilities(streaming=False, interim_results=False)
        )
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._language = language

    def _get_model(self) -> WhisperModel:
        return _load_model(self._model_size, self._device, self._compute_type)

    async def recognize(
        self,
        buffer: utils.AudioBuffer,
        *,
        language: str | None = None,
    ) -> SpeechEvent:
        t0 = time.monotonic()

        # Convert LiveKit AudioBuffer to numpy array
        audio_bytes = b"".join(
            frame.data for frame in buffer
        )
        audio_array = _downsample(audio_bytes)

        if len(audio_array) < 1600:  # < 0.1s — too short, skip
            return SpeechEvent(
                type=SpeechEventType.FINAL_TRANSCRIPT,
                alternatives=[SpeechData(text="", language="en", confidence=0.0)],
            )

        model = self._get_model()
        lang_hint = language or self._language

        loop = asyncio.get_event_loop()
        transcript, detected_lang, confidence = await loop.run_in_executor(
            _STT_EXECUTOR,
            _transcribe_sync,
            audio_array,
            model,
            lang_hint,
        )

        latency_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            f"STT: lang={detected_lang} conf={confidence:.2f} "
            f"len={len(transcript)} latency={latency_ms}ms"
        )

        return SpeechEvent(
            type=SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[
                SpeechData(
                    text=transcript,
                    language=detected_lang,
                    confidence=confidence,
                )
            ],
        )
