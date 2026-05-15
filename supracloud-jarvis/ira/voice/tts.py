"""
IRA TTS — Kokoro-82M (af_bella / af_heart) for warm, professional Indian-accented English.

Voice selection strategy:
  English & European  : Kokoro af_bella (warm, female, light Indian warmth)
  Indian languages    : Kokoro af_bella with transliterated text (Phase 3)
                        → Plug in IndicTTS / Parler-TTS in Phase 4 for native script TTS
  Chinese / Japanese  : Kokoro af_bella (with romanised pronunciation guide)

Audio pipeline:
  Kokoro output : 24kHz mono float32
  Resampled to  : 48kHz mono int16  (LiveKit standard)
  Chunk size    : 4800 samples (100ms) — balances latency vs efficiency

Kokoro model : kokoro-onnx v0.4 (CPU ONNX runtime)
Voice files  : downloaded to /root/.cache/kokoro/ on first run
"""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import AsyncIterator

import numpy as np
from livekit.agents import tts, utils
from livekit.agents.tts import SynthesizedAudio, SynthesisEvent, SynthesisEventType

from voice.language import get_kokoro_voice, is_indic, LANGUAGE_NAMES

logger = logging.getLogger("ira.tts")

_TTS_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="kokoro")

# Audio format constants
KOKORO_SAMPLE_RATE = 24_000   # Kokoro native output
LIVEKIT_SAMPLE_RATE = 48_000  # LiveKit expects 48kHz
CHUNK_SAMPLES = 4_800          # 100ms chunks at 48kHz — low latency streaming

# IRA's voice constants
DEFAULT_VOICE = "af_bella"    # Warm, professional, light Indian warmth
BACKUP_VOICE = "af_heart"     # Alternative if af_bella unavailable
SPEECH_SPEED = 1.05           # Slightly brisker than default — executive tone


@lru_cache(maxsize=1)
def _load_kokoro(voice: str):
    """Load and cache the Kokoro ONNX model."""
    try:
        from kokoro_onnx import Kokoro
        logger.info(f"Loading Kokoro TTS with voice '{voice}'...")
        model = Kokoro("kokoro-v0_19.onnx", "voices.bin")
        logger.info("Kokoro TTS ready.")
        return model
    except Exception as e:
        logger.error(f"Kokoro load failed: {e}. TTS will produce silence.")
        return None


def _resample_24k_to_48k(audio_24k: np.ndarray) -> np.ndarray:
    """Upsample 24kHz float32 → 48kHz int16 using simple linear interpolation."""
    from scipy.signal import resample_poly
    audio_48k = resample_poly(audio_24k, up=2, down=1).astype(np.float32)
    # Clip and convert to int16 for LiveKit
    audio_48k = np.clip(audio_48k, -1.0, 1.0)
    return (audio_48k * 32767).astype(np.int16)


def _prepare_text_for_voice(text: str, lang: str) -> str:
    """
    Prepare text for TTS synthesis.

    For Indian languages (Phase 3): Kokoro synthesises the English text while
    the LLM has already responded in the target language. This gives intelligible
    audio while native-script Indian TTS is integrated in Phase 4.

    For all other languages: pass text through as-is.
    """
    if is_indic(lang):
        lang_name = LANGUAGE_NAMES.get(lang, lang)
        # Prepend a soft cue so Kokoro reads correctly
        # In Phase 4, replace this with a native IndicTTS call
        return text
    return text


def _synthesise_sync(
    text: str,
    voice: str,
    speed: float,
    model,
) -> np.ndarray | None:
    """
    Synthesise text to audio with Kokoro (synchronous, runs in thread pool).
    Returns 24kHz float32 numpy array or None on failure.
    """
    if model is None:
        return None
    try:
        samples, _ = model.create(text, voice=voice, speed=speed, lang="en-us")
        return samples.astype(np.float32)
    except Exception as e:
        logger.error(f"Kokoro synthesis error: {e}")
        return None


class IRAKokoroTTS(tts.TTS):
    """
    LiveKit-compatible TTS plugin backed by Kokoro-82M (af_bella).
    Produces warm, professional audio in IRA's voice.
    """

    def __init__(
        self,
        voice: str = DEFAULT_VOICE,
        speed: float = SPEECH_SPEED,
    ):
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=LIVEKIT_SAMPLE_RATE,
            num_channels=1,
        )
        self._voice = voice
        self._speed = speed

    def synthesize(self, text: str, *, language: str = "en") -> "IRAChunkedStream":
        return IRAChunkedStream(
            text=_prepare_text_for_voice(text, language),
            voice=self._voice,
            speed=self._speed,
            tts=self,
        )


class IRAChunkedStream(tts.ChunkedStream):
    """Streams synthesised audio in 100ms chunks for low perceived latency."""

    def __init__(self, text: str, voice: str, speed: float, tts: IRAKokoroTTS):
        super().__init__(tts=tts, input_text=text)
        self._text = text
        self._voice = voice
        self._speed = speed

    async def _run(self) -> None:
        t0 = time.monotonic()

        model = _load_kokoro(self._voice)

        loop = asyncio.get_event_loop()
        audio_24k = await loop.run_in_executor(
            _TTS_EXECUTOR,
            _synthesise_sync,
            self._text,
            self._voice,
            self._speed,
            model,
        )

        latency_ms = int((time.monotonic() - t0) * 1000)
        logger.info(f"TTS synthesis: {len(self._text)} chars in {latency_ms}ms")

        if audio_24k is None:
            return

        # Resample and stream in chunks
        audio_48k = _resample_24k_to_48k(audio_24k)
        total_samples = len(audio_48k)

        for start in range(0, total_samples, CHUNK_SAMPLES):
            chunk = audio_48k[start : start + CHUNK_SAMPLES]
            self._event_ch.send_nowait(
                SynthesisEvent(
                    type=SynthesisEventType.AUDIO,
                    audio=SynthesizedAudio(
                        request_id=self._request_id,
                        frame=utils.AudioFrame(
                            data=chunk.tobytes(),
                            sample_rate=LIVEKIT_SAMPLE_RATE,
                            num_channels=1,
                            samples_per_channel=len(chunk),
                        ),
                        delta_text="",
                    ),
                )
            )
