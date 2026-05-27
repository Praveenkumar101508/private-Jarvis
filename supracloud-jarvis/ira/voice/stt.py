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
import threading
import time
from concurrent.futures import ThreadPoolExecutor
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


# Fix #124: thread-safe Whisper model cache — same double-checked locking pattern
# as _load_kokoro in tts.py, preventing duplicate model loads on concurrent calls.
# Fix #129: model download errors are caught and re-raised with a descriptive
# message so operators know to check disk space and network connectivity rather
# than seeing a bare exception from the Hugging Face downloader.
_whisper_model: WhisperModel | None = None
_whisper_loaded: bool = False
_whisper_lock = threading.Lock()


def _load_model(model_size: str, device: str, compute_type: str) -> WhisperModel:
    """Load and cache the Whisper model (Fix #124: thread-safe, Fix #129: clear errors)."""
    global _whisper_model, _whisper_loaded
    if _whisper_loaded:             # Fast path
        if _whisper_model is None:
            raise RuntimeError(
                f"Whisper {model_size} is unavailable — check startup logs for the download error."
            )
        return _whisper_model
    with _whisper_lock:
        if _whisper_loaded:         # Race guard
            if _whisper_model is None:
                raise RuntimeError(
                    f"Whisper {model_size} is unavailable — check startup logs for the download error."
                )
            return _whisper_model
        logger.info(f"Loading Whisper {model_size} on {device} ({compute_type})...")
        try:
            _whisper_model = WhisperModel(model_size, device=device, compute_type=compute_type)
            logger.info("Whisper model loaded.")
        except Exception as e:
            # Fix #129: surface download/init errors with actionable context so the
            # operator knows what to fix (disk space, network, CUDA availability).
            logger.error(
                f"Whisper {model_size} failed to load: {e}. "
                f"Ensure network access is available for the initial model download "
                f"and that the host has sufficient disk space (~3 GB for large-v3)."
            )
            _whisper_model = None
        finally:
            _whisper_loaded = True
        if _whisper_model is None:
            raise RuntimeError(
                f"Whisper {model_size} is unavailable — see above error for details."
            )
        return _whisper_model


def _downsample(audio_bytes: bytes) -> np.ndarray:
    """Convert 48kHz int16 PCM bytes to 16kHz float32 array for Whisper.

    Uses scipy.signal.resample_poly instead of naive decimation (pcm[::3]).
    Naive slice-based decimation causes aliasing artifacts because it skips
    samples without first applying a low-pass anti-aliasing filter — this
    degrades STT accuracy on high-frequency speech sounds (sibilants, etc.).
    resample_poly applies a polyphase anti-aliasing FIR filter automatically.
    """
    pcm = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    try:
        from scipy.signal import resample_poly
        return resample_poly(pcm, up=1, down=DOWNSAMPLE_RATIO).astype(np.float32)
    except ImportError:
        # Graceful fallback if scipy is not installed — log and use basic decimation
        logger.warning("scipy not installed; using aliasing-prone decimation. Add scipy to requirements.")
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

        loop = asyncio.get_running_loop()
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
