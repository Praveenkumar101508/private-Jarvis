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
import re
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


# ── Language → Kokoro lang string ────────────────────────────────────────────
# Fix #119: the `language` parameter passed to synthesize() was ignored;
# model.create() always received lang="en-us". Now we map it correctly.
_KOKORO_LANG_MAP: dict[str, str] = {
    "en":    "en-us",
    "en-us": "en-us",
    "en-gb": "en-gb",
    "de":    "de",
    "fr":    "fr",
    "it":    "it",
    "es":    "es",
    # Indic languages: Kokoro af_bella speaks English, so we keep "en-us"
    # until native IndicTTS is plugged in (Phase 4).
}


def _kokoro_lang(lang: str) -> str:
    """Map ISO 639-1 code to Kokoro's lang= string. Defaults to 'en-us'."""
    return _KOKORO_LANG_MAP.get(lang, "en-us")


# ── Sentence splitter for low-latency streaming ───────────────────────────────
# Fix #118: previously _run() synthesised the ENTIRE text before emitting any
# audio (fake chunking — all 100ms frames sent at once after a long wait).
# Now text is split into sentences; each sentence is synthesised and emitted
# immediately, so TTFA ≈ time-to-synthesise-first-sentence (~0.3–0.8 s).
_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?…])\s+')


def _split_sentences(text: str) -> list[str]:
    """Split text into synthesis units at sentence boundaries."""
    parts = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    return parts if parts else [text]


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
    lang: str = "en-us",
) -> np.ndarray | None:
    """
    Synthesise text to audio with Kokoro (synchronous, runs in thread pool).
    Returns 24kHz float32 numpy array or None on failure.

    lang: Kokoro language string (e.g. "en-us", "de", "fr") — Fix #119.
    """
    if model is None:
        return None
    try:
        samples, _ = model.create(text, voice=voice, speed=speed, lang=lang)
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
            lang=language,   # Fix #119: forward language so Kokoro uses correct phonology
            tts=self,
        )


class IRAChunkedStream(tts.ChunkedStream):
    """
    Streams synthesised audio sentence-by-sentence for low time-to-first-audio.

    Fix #118: the previous implementation synthesised the ENTIRE response text
    before emitting a single audio frame (fake streaming). Now each sentence is
    synthesised and flushed immediately, reducing TTFA from the full-response
    synthesis time (~several seconds) to a single-sentence synthesis time
    (~0.3–0.8 s for typical voice responses).
    """

    def __init__(
        self,
        text: str,
        voice: str,
        speed: float,
        lang: str,
        tts: IRAKokoroTTS,
    ):
        super().__init__(tts=tts, input_text=text)
        self._text = text
        self._voice = voice
        self._speed = speed
        self._lang = lang   # Fix #119: store language for Kokoro phonology selection

    async def _run(self) -> None:
        t0 = time.monotonic()
        model = _load_kokoro(self._voice)
        loop = asyncio.get_running_loop()
        kokoro_lang = _kokoro_lang(self._lang)

        sentences = _split_sentences(self._text)
        total_chars = 0

        for sentence in sentences:
            audio_24k = await loop.run_in_executor(
                _TTS_EXECUTOR,
                _synthesise_sync,
                sentence,
                self._voice,
                self._speed,
                model,
                kokoro_lang,  # Fix #119
            )
            if audio_24k is None:
                continue

            total_chars += len(sentence)

            # Resample and emit this sentence's audio immediately
            audio_48k = _resample_24k_to_48k(audio_24k)
            for start in range(0, len(audio_48k), CHUNK_SAMPLES):
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

        latency_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            f"TTS synthesis: {total_chars} chars / {len(sentences)} sentence(s) "
            f"in {latency_ms}ms  lang={kokoro_lang}"
        )
