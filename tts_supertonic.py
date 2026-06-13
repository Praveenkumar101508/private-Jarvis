"""
IRA TTS — Supertonic-3 (on-device, ONNX) drop-in for IRAKokoroTTS.

WHY: Supertonic is a 99M-param, MIT-licensed, fully on-device TTS (no cloud, no
GPU required) with a clean female voice set and a 44.1 kHz studio-grade output.
It fits IRA's sovereignty thesis better than Kokoro and ships its own local
OpenAI-compatible server (`supertonic serve`) for the browser path. This module
is the in-process LiveKit plugin path (mirrors voice/tts.py exactly), so swapping
engines is a one-line change in voice/agent.py — nothing else in IRA changes.

VOICE: defaults to a FEMALE voice. Supertonic-3 ships 10 built-in voices:
M1–M5 (male) and F1–F5 (female). IRA_VOICE picks one; default "F1".

LANGUAGE: Supertonic-3 supports 31 languages incl. Hindi ("hi"). Tamil/Telugu/
Kannada/Malayalam are NOT in that set, so they route to the built-in language-
agnostic fallback ("na") — intelligible, not native-script-perfect. (This mirrors
the Kokoro era, where Indic text was read by an English voice. Native Indic TTS
remains a later enhancement.)

AUDIO PIPELINE (identical contract to voice/tts.py so the LiveKit side is unchanged):
  Supertonic output : 44.1 kHz mono float32, shape (1, N)
  Resampled to       : 48 kHz mono int16   (LiveKit standard) via 160/147 poly
  Streaming          : sentence-by-sentence for low time-to-first-audio

Model files download to Supertonic's own cache on first run (auto_download=True).

Config via env:
  IRA_VOICE          voice style name (M1–M5 / F1–F5). Default "F1" (female).
  IRA_TTS_STEPS      synthesis steps 5(low)–12(high). Default 8 (medium).
  SUPERTONIC_MODEL   model name. Default "supertonic-3".
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from livekit.agents import tts, utils
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions

from voice.language import is_indic

logger = logging.getLogger("ira.tts.supertonic")

_TTS_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="supertonic")

# Audio format constants
SUPERTONIC_SAMPLE_RATE = 44_100   # supertonic-3 native output
LIVEKIT_SAMPLE_RATE = 48_000      # LiveKit expects 48kHz
CHUNK_SAMPLES = 4_800             # 100ms chunks at 48kHz — low latency streaming

# IRA voice constants
DEFAULT_VOICE = os.getenv("IRA_VOICE", "F1")     # FEMALE by default (F1–F5 female, M1–M5 male)
DEFAULT_STEPS = int(os.getenv("IRA_TTS_STEPS", "8"))
SPEECH_SPEED = 1.05                              # matches the Kokoro-era executive tone
_MODEL_NAME = os.getenv("SUPERTONIC_MODEL", "supertonic-3")

# The 31 languages supertonic-3 supports natively. Anything else → "na" fallback.
_SUPERTONIC_LANGS: frozenset[str] = frozenset({
    "en", "ko", "ja", "ar", "bg", "cs", "da", "de", "el", "es", "et", "fi",
    "fr", "hi", "hr", "hu", "id", "it", "lt", "lv", "nl", "pl", "pt", "ro",
    "ru", "sk", "sl", "sv", "tr", "uk", "vi",
})
_NA = "na"  # language-agnostic fallback token built into Supertonic


def _supertonic_lang(lang: str | None) -> str:
    """Map an IRA ISO 639-1 code to a Supertonic lang string.

    - Directly supported (incl. Hindi 'hi') → pass through.
    - Indic-but-unsupported (ta/te/kn/ml) and any unknown code → 'na'
      (language-agnostic fallback; intelligible without a native adapter).
    """
    if not lang:
        return _NA
    code = lang.lower().split("-")[0]
    if code in _SUPERTONIC_LANGS:
        return code
    # is_indic catches ta/te/kn/ml (hi already returned above); all fall through to na
    if is_indic(code):
        return _NA
    return _NA


# ── Sentence splitter for low-latency streaming (same contract as voice/tts.py) ──
_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?…])\s+')


def _split_sentences(text: str) -> list[str]:
    parts = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    return parts if parts else [text]


# ── Thread-safe Supertonic model + voice-style cache (double-checked locking) ────
# Same rationale as Kokoro's Fix #124: lru_cache is not safe against concurrent
# first-calls in Python < 3.12. We construct the engine exactly once and cache the
# resolved voice Style object alongside it.
_engine: object = None             # supertonic.TTS instance or None if load failed
_voice_style: object = None        # resolved Style for DEFAULT_VOICE
_loaded: bool = False
_lock = threading.Lock()


def _load_engine(voice: str):
    """Load + cache the Supertonic engine and the owner's voice style (singleton)."""
    global _engine, _voice_style, _loaded
    if _loaded:
        return _engine, _voice_style
    with _lock:
        if _loaded:
            return _engine, _voice_style
        try:
            from supertonic import TTS  # installed on the Shadow box: pip install supertonic
            logger.info(f"Loading Supertonic '{_MODEL_NAME}' with voice '{voice}'...")
            engine = TTS(model=_MODEL_NAME, auto_download=True)
            try:
                style = engine.get_voice_style(voice)
            except Exception as e:
                logger.error(f"Voice '{voice}' not found ({e}); falling back to 'F1'.")
                style = engine.get_voice_style("F1")
            _engine, _voice_style = engine, style
            logger.info(
                f"Supertonic ready (sample_rate={getattr(engine, 'sample_rate', SUPERTONIC_SAMPLE_RATE)}Hz, "
                f"voices={getattr(engine, 'voice_style_names', '?')})."
            )
        except Exception as e:
            logger.error(f"Supertonic load failed: {e}. TTS will produce silence.")
            _engine, _voice_style = None, None
        finally:
            _loaded = True
        return _engine, _voice_style


def _resample_44k_to_48k(audio_44k: np.ndarray) -> np.ndarray:
    """Resample 44.1kHz float32 → 48kHz int16. 48000/44100 = 160/147 (poly)."""
    from scipy.signal import resample_poly
    audio = np.asarray(audio_44k, dtype=np.float32).reshape(-1)  # (1, N) → (N,)
    audio_48k = resample_poly(audio, up=160, down=147).astype(np.float32)
    audio_48k = np.clip(audio_48k, -1.0, 1.0)
    return (audio_48k * 32767).astype(np.int16)


def _synthesise_sync(text: str, speed: float, steps: int, engine, style, lang: str):
    """Synthesise one unit with Supertonic (sync; runs in the thread pool).

    Returns 44.1kHz float32 (1, N) or None on failure.
    """
    if engine is None or style is None:
        return None
    try:
        wav, _dur = engine.synthesize(
            text=text,
            voice_style=style,
            total_steps=steps,
            speed=speed,
            lang=lang,            # "na" for unsupported langs; engine handles the token
        )
        return np.asarray(wav, dtype=np.float32)
    except Exception as e:
        logger.error(f"Supertonic synthesis error: {e}")
        return None


class IRASupertonicTTS(tts.TTS):
    """LiveKit Agents 1.x TTS plugin backed by Supertonic-3.

    Drop-in for IRAKokoroTTS: same constructor shape (voice, speed), same
    streaming=False capability, same 48kHz/int16 output contract.
    """

    def __init__(self, voice: str = DEFAULT_VOICE, speed: float = SPEECH_SPEED):
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=LIVEKIT_SAMPLE_RATE,
            num_channels=1,
        )
        self._voice = voice
        self._speed = speed

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> "IRASupertonicChunkedStream":
        return IRASupertonicChunkedStream(tts=self, input_text=text, conn_options=conn_options)


class IRASupertonicChunkedStream(tts.ChunkedStream):
    """Synthesises sentence-by-sentence for low TTFA, pushing each sentence's PCM
    to the 1.x AudioEmitter as soon as it's ready."""

    def __init__(self, *, tts: IRASupertonicTTS, input_text: str, conn_options):
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._voice = tts._voice
        self._speed = tts._speed

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        t0 = time.monotonic()
        engine, style = _load_engine(self._voice)
        loop = asyncio.get_running_loop()
        # The LLM already replied in the target language; the synth language is
        # resolved per the engine's supported set (Hindi native, others → "na").
        lang = _supertonic_lang(os.getenv("IRA_TTS_LANG", "en"))

        output_emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=LIVEKIT_SAMPLE_RATE,
            num_channels=1,
            mime_type="audio/pcm",
        )

        sentences = _split_sentences(self.input_text)
        total_chars = 0

        for sentence in sentences:
            audio_44k = await loop.run_in_executor(
                _TTS_EXECUTOR, _synthesise_sync,
                sentence, self._speed, DEFAULT_STEPS, engine, style, lang,
            )
            if audio_44k is None:
                continue
            total_chars += len(sentence)
            audio_48k = _resample_44k_to_48k(audio_44k)
            output_emitter.push(audio_48k.tobytes())

        output_emitter.flush()
        latency_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            f"Supertonic synthesis: {total_chars} chars / {len(sentences)} sentence(s) "
            f"in {latency_ms}ms  voice={self._voice} lang={lang}"
        )


# ── Standalone smoke test (run on the Shadow box) ─────────────────────────────
# Usage:  python -m voice.tts_supertonic "Hello, I am IRA." [out.wav] [F1]
# Synthesises a sentence to a WAV file (no LiveKit), verifying the Supertonic path.
if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    text = sys.argv[1] if len(sys.argv) > 1 else "Hello, I am IRA, your assistant."
    out = sys.argv[2] if len(sys.argv) > 2 else "ira_supertonic_smoke.wav"
    voice = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_VOICE
    eng, sty = _load_engine(voice)
    if eng is None:
        print("Supertonic unavailable — run `pip install supertonic` and check the model download.")
        raise SystemExit(1)
    samples = _synthesise_sync(text, SPEECH_SPEED, DEFAULT_STEPS, eng, sty, _supertonic_lang("en"))
    if samples is None:
        print("Synthesis failed — see log above.")
        raise SystemExit(1)
    import soundfile as sf  # type: ignore
    sf.write(out, np.asarray(samples, dtype=np.float32).reshape(-1), SUPERTONIC_SAMPLE_RATE)
    print(f"wrote {out} ({np.asarray(samples).size} samples @ {SUPERTONIC_SAMPLE_RATE}Hz, voice={voice})")
