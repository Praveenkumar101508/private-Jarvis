"""
Local STT via faster-whisper — runs entirely on-device (MacBook Air M1 / CUDA).
Implements the LiveKit STT plugin interface so it drops into VoiceAssistant
without any cloud dependency.
"""
from __future__ import annotations

import asyncio
import io
import logging
from dataclasses import dataclass
from typing import AsyncIterator

import numpy as np

log = logging.getLogger("ira.voice.local_stt")

_model_cache: dict[str, "WhisperModel"] = {}


def _get_model(model_size: str, device: str, compute_type: str) -> "WhisperModel":
    key = f"{model_size}:{device}:{compute_type}"
    if key not in _model_cache:
        from faster_whisper import WhisperModel
        log.info("Loading faster-whisper model", model=model_size, device=device)
        _model_cache[key] = WhisperModel(model_size, device=device, compute_type=compute_type)
        log.info("faster-whisper model loaded")
    return _model_cache[key]


@dataclass
class LocalSTTOptions:
    model_size: str = "base"
    device: str = "auto"
    compute_type: str = "int8"
    language: str | None = None
    beam_size: int = 5
    vad_filter: bool = True


class LocalSTT:
    """
    Drop-in LiveKit STT plugin backed by faster-whisper.
    Accepts raw PCM frames (16-bit, 16 kHz, mono) and returns transcription.
    """

    def __init__(self, opts: LocalSTTOptions | None = None):
        self._opts = opts or LocalSTTOptions()

    def _load(self) -> "WhisperModel":
        return _get_model(
            self._opts.model_size,
            self._opts.device,
            self._opts.compute_type,
        )

    async def recognize(self, audio_bytes: bytes, sample_rate: int = 16000) -> str:
        """Transcribe a complete audio buffer (offline / turn-end)."""
        model = await asyncio.get_event_loop().run_in_executor(None, self._load)
        return await asyncio.get_event_loop().run_in_executor(
            None, self._transcribe_sync, model, audio_bytes, sample_rate
        )

    def _transcribe_sync(
        self, model: "WhisperModel", audio_bytes: bytes, sample_rate: int
    ) -> str:
        audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        if sample_rate != 16000:
            # simple linear resample — faster-whisper expects 16 kHz
            ratio = 16000 / sample_rate
            target_len = int(len(audio_np) * ratio)
            audio_np = np.interp(
                np.linspace(0, len(audio_np) - 1, target_len),
                np.arange(len(audio_np)),
                audio_np,
            )

        segments, info = model.transcribe(
            audio_np,
            language=self._opts.language,
            beam_size=self._opts.beam_size,
            vad_filter=self._opts.vad_filter,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        log.debug("STT result", text=text, lang=info.language)
        return text
