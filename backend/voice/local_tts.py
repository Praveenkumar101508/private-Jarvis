"""
Local TTS via kokoro ONNX — runs entirely on-device (no cloud, no API key).
Kokoro produces natural-sounding speech from an ONNX model file.
Returns raw PCM bytes (24 kHz, mono, float32 → int16) ready for LiveKit.
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import struct
import wave
from pathlib import Path

log = logging.getLogger("ira.voice.local_tts")

_pipeline_cache: dict[str, object] = {}

# Default model path — override via KOKORO_MODEL_PATH env var
DEFAULT_MODEL_PATH = os.getenv(
    "KOKORO_MODEL_PATH",
    str(Path(__file__).parent / "models" / "kokoro-v0_19.onnx"),
)
DEFAULT_VOICES_PATH = os.getenv(
    "KOKORO_VOICES_PATH",
    str(Path(__file__).parent / "models" / "voices.bin"),
)


def _get_pipeline(model_path: str, voices_path: str) -> object:
    if model_path not in _pipeline_cache:
        from kokoro_onnx import Kokoro
        log.info("Loading kokoro ONNX model", path=model_path)
        _pipeline_cache[model_path] = Kokoro(model_path, voices_path)
        log.info("Kokoro model loaded")
    return _pipeline_cache[model_path]


class LocalTTS:
    """
    Drop-in TTS provider backed by kokoro ONNX.
    Returns WAV bytes (24 kHz mono) for a given text input.
    Voice default: 'af_sarah' (warm female, Indian-accent variant).
    """

    def __init__(
        self,
        model_path: str = DEFAULT_MODEL_PATH,
        voices_path: str = DEFAULT_VOICES_PATH,
        voice: str = "af_sarah",
        speed: float = 1.0,
        lang: str = "en-us",
    ):
        self._model_path = model_path
        self._voices_path = voices_path
        self._voice = voice
        self._speed = speed
        self._lang = lang

    async def synthesize(self, text: str) -> bytes:
        """Return WAV bytes for the given text."""
        pipeline = await asyncio.get_event_loop().run_in_executor(
            None, _get_pipeline, self._model_path, self._voices_path
        )
        wav_bytes = await asyncio.get_event_loop().run_in_executor(
            None, self._synth_sync, pipeline, text
        )
        return wav_bytes

    def _synth_sync(self, pipeline: object, text: str) -> bytes:
        import numpy as np

        samples, sample_rate = pipeline.create(
            text,
            voice=self._voice,
            speed=self._speed,
            lang=self._lang,
        )
        # Convert float32 → int16 PCM, then wrap in WAV container
        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(sample_rate)
            wf.writeframes(pcm.tobytes())
        log.debug("TTS synthesized", chars=len(text), sample_rate=sample_rate)
        return buf.getvalue()
