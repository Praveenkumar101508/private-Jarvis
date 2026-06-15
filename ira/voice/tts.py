"""IRA TTS — Kokoro-82M (af_bella) via kokoro-onnx 0.4.7, livekit-agents 1.5.x."""
from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import numpy as np
from livekit import rtc
from livekit.agents import tts
from livekit.agents.tts import SynthesizedAudio

logger = logging.getLogger("ira.tts")

_TTS_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="kokoro")

KOKORO_SAMPLE_RATE = 24_000
LIVEKIT_SAMPLE_RATE = 48_000
CHUNK_SAMPLES = 4_800  # 100ms at 48kHz

DEFAULT_VOICE = "af_bella"
SPEECH_SPEED  = 1.05


@lru_cache(maxsize=1)
def _load_kokoro(_voice: str):
    """Load Kokoro model — downloads from HuggingFace on first call (~330MB)."""
    try:
        from kokoro_onnx import Kokoro
        from huggingface_hub import hf_hub_download

        logger.info("Loading Kokoro TTS model (downloading if needed)...")
        model_path = hf_hub_download(repo_id="hexgrad/Kokoro-82M", filename="kokoro-v0_19.onnx")
        # Try v1_0 name first; fall back to original name
        try:
            voices_path = hf_hub_download(repo_id="hexgrad/Kokoro-82M", filename="voices-v1_0.bin")
        except Exception:
            voices_path = hf_hub_download(repo_id="hexgrad/Kokoro-82M", filename="voices.bin")
        model = Kokoro(model_path, voices_path)
        logger.info("Kokoro TTS ready.")
        return model
    except Exception as e:
        logger.error(f"Kokoro load failed: {e}. TTS will be silent.")
        return None


def _resample_24k_to_48k(audio_24k: np.ndarray) -> np.ndarray:
    from scipy.signal import resample_poly
    audio_48k = resample_poly(audio_24k, up=2, down=1).astype(np.float32)
    audio_48k = np.clip(audio_48k, -1.0, 1.0)
    return (audio_48k * 32767).astype(np.int16)


def _synthesise_sync(text: str, voice: str, speed: float, model) -> np.ndarray | None:
    if model is None:
        return None
    try:
        samples, _ = model.create(text, voice=voice, speed=speed, lang="en-us")
        return samples.astype(np.float32)
    except Exception as e:
        logger.error(f"Kokoro synthesis error: {e}")
        return None


class IRAKokoroTTS(tts.TTS):
    def __init__(self, voice: str = DEFAULT_VOICE, speed: float = SPEECH_SPEED):
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=LIVEKIT_SAMPLE_RATE,
            num_channels=1,
        )
        self._voice = voice
        self._speed = speed

    def synthesize(self, text: str, *, language: str = "en") -> "IRAChunkedStream":
        return IRAChunkedStream(text=text, voice=self._voice, speed=self._speed, tts=self)


class IRAChunkedStream(tts.ChunkedStream):
    def __init__(self, text: str, voice: str, speed: float, tts: IRAKokoroTTS):
        super().__init__(tts=tts, input_text=text)
        self._text  = text
        self._voice = voice
        self._speed = speed

    async def _run(self) -> None:
        t0 = time.monotonic()
        model = _load_kokoro(self._voice)

        loop = asyncio.get_running_loop()
        audio_24k = await loop.run_in_executor(
            _TTS_EXECUTOR, _synthesise_sync, self._text, self._voice, self._speed, model
        )

        logger.info(f"TTS: {len(self._text)} chars in {int((time.monotonic()-t0)*1000)}ms")

        if audio_24k is None:
            return

        audio_48k = _resample_24k_to_48k(audio_24k)
        for start in range(0, len(audio_48k), CHUNK_SAMPLES):
            chunk = audio_48k[start : start + CHUNK_SAMPLES]
            self._event_ch.send_nowait(
                SynthesizedAudio(
                    request_id=self._request_id,
                    frame=rtc.AudioFrame(
                        data=chunk.tobytes(),
                        sample_rate=LIVEKIT_SAMPLE_RATE,
                        num_channels=1,
                        samples_per_channel=len(chunk),
                    ),
                    delta_text="",
                )
            )
