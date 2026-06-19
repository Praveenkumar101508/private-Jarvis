"""voice/voice_output.py — close the voice loop: make IRA actually TALK.

Subscribes to the brain's on_speak events and plays them aloud: synthesize via the
SELECTED TTS engine (carrying affect expression when the affect layer is on) →
local audio playback on the box. This is what turns the wake-word command flow,
autonomous brain speech, and the affective voice into something you actually hear.

Primary output is LOCAL PLAYBACK (the at-home smart-speaker model). LiveKit
remote-room publishing is intentionally NOT here — that belongs to the mobile-app
work. The existing /ws/brain speak frames keep flowing; local playback is additive.

Flag-gated by IRA_VOICE_OUTPUT (default "none"; "local" enables playback). Fully
fail-soft: no audio device / TTS error → log and skip, never crash IRA. Utterances
are synthesized + played on a background worker, one at a time (no overlap), and
dropped if the queue backs up. Heavy deps (sounddevice/numpy) are lazy-imported so
this module loads in the lightweight (no-audio) test env.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import os
import wave
from typing import Callable, Optional, Protocol

logger = logging.getLogger("ira.voice.output")


def output_mode() -> str:
    """Selected voice-output mode: "local" plays aloud; anything else = frames only."""
    return os.getenv("IRA_VOICE_OUTPUT", "none").strip().lower()


# ── Seams (real impls lazy-import heavy deps; tests inject fakes) ─────────────

class AudioSink(Protocol):
    def play(self, wav_bytes: bytes) -> None: ...


def _default_synth(text: str, *, instruct: Optional[str] = None,
                   speed: Optional[float] = None) -> bytes:
    """Synthesize via the selected TTS engine → WAV bytes (carries affect when given)."""
    from voice.tts_factory import synthesize_say

    return synthesize_say(text, instruct=instruct, speed=speed)


class LocalAudioSink:
    """Play a WAV byte string through the default output device via sounddevice."""

    def play(self, wav_bytes: bytes) -> None:
        import numpy as np
        import sounddevice as sd

        with wave.open(io.BytesIO(wav_bytes)) as wf:
            rate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())
        if not frames:
            return
        audio = np.frombuffer(frames, dtype="<i2")
        sd.play(audio, rate)   # PortAudio handles device-rate conversion
        sd.wait()


# ── The output worker ────────────────────────────────────────────────────────

class VoiceOutput:
    """Serializes speak events into synth+play on a background worker.

    Seams (synth, sink, voice_style) are injectable so the flow is testable without
    a TTS engine or audio device.
    """

    def __init__(
        self,
        *,
        synth: Callable[..., bytes] = _default_synth,
        sink: Optional[AudioSink] = None,
        voice_style: Optional[Callable[[], Optional[dict]]] = None,
        max_queue: int = 8,
    ):
        self._synth = synth
        self._sink = sink if sink is not None else LocalAudioSink()
        self._voice_style = voice_style
        self._q: "asyncio.Queue[Optional[str]]" = asyncio.Queue(maxsize=max_queue)
        self.running = False

    def handler(self, text: str) -> None:
        """on_speak subscriber — enqueue without blocking the brain; drop if backed up."""
        text = (text or "").strip()
        if not text:
            return
        try:
            self._q.put_nowait(text)
        except asyncio.QueueFull:
            logger.warning("voice output backed up — dropping utterance")

    def stop(self) -> None:
        self.running = False
        with contextlib.suppress(asyncio.QueueFull):
            self._q.put_nowait(None)   # wake the worker so it can exit

    async def run(self) -> None:
        self.running = True
        loop = asyncio.get_running_loop()
        logger.info("Voice output worker online (local playback).")
        while self.running:
            text = await self._q.get()
            if text is None:
                break
            try:
                style = self._voice_style() if self._voice_style else None
                instruct = style.get("instruct") if style else None
                speed = style.get("speed") if style else None
                wav = await loop.run_in_executor(
                    None, lambda: self._synth(text, instruct=instruct, speed=speed))
                if wav:
                    await loop.run_in_executor(None, self._sink.play, wav)
            except Exception as exc:  # noqa: BLE001 - one bad utterance must not stop the voice
                logger.warning("voice output failed (non-fatal): %s", exc)


# ── Lifecycle (called from main.lifespan, after the brain is up) ─────────────

async def start_voice_output(app, brain) -> None:
    """Attach local playback to the brain's speech. No-op unless IRA_VOICE_OUTPUT=local
    and a brain exists. Fail-soft so it can never block startup."""
    if output_mode() != "local":
        logger.info("Voice output disabled (set IRA_VOICE_OUTPUT=local to enable)")
        return
    if brain is None:
        logger.info("Voice output: no brain to attach to — skipping")
        return
    try:
        voice_style = None
        if getattr(brain, "affect", None) is not None:
            voice_style = brain.affect.voice_style   # affect → instruct/speed when on
        vo = VoiceOutput(voice_style=voice_style)
        brain.on_speak(vo.handler)
        app.state.voice_output = vo
        task = asyncio.create_task(vo.run())
        task.add_done_callback(
            lambda t: t.cancelled() or (t.exception() and logger.warning(
                "Voice output worker ended: %s", t.exception())))
        app.state.voice_output_task = task
        logger.info("Voice output online (local playback)")
    except Exception as exc:  # noqa: BLE001 - never block startup
        logger.warning("Voice output failed to start (non-fatal): %s", exc)
        app.state.voice_output = None


async def stop_voice_output(app) -> None:
    vo = getattr(app.state, "voice_output", None)
    brain = getattr(app.state, "brain", None)
    if vo is not None:
        if brain is not None:
            with contextlib.suppress(Exception):
                brain.off_speak(vo.handler)
        vo.stop()
    task = getattr(app.state, "voice_output_task", None)
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        app.state.voice_output_task = None
    app.state.voice_output = None


__all__ = [
    "output_mode", "VoiceOutput", "LocalAudioSink", "AudioSink",
    "start_voice_output", "stop_voice_output",
]
