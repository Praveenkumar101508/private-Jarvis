"""voice/wakeword.py — always-on, owner-gated wake-word trigger (the voice front door).

Smart-speaker pattern for a LOCAL microphone on the Shadow box: openWakeWord
(Apache-2.0, CPU, ONNX) listens continuously; on a hit, IRA's EXISTING ECAPA
owner-gate verifies it's actually you before anything happens; then faster-whisper
transcribes the command and it's injected into the brain via the existing
feed_percept seam — exactly like the /voice/transcribe path.

INPUT path only. This is the missing front door: it gets the owner's spoken command
INTO the brain. The brain's spoken *reply* still goes out as `speak` frames over
/ws/brain — wiring those to server-side TTS playback is the separate, deferred
on_speak→TTS item.

OFF by default (IRA_WAKEWORD_ENABLED). Fully fail-soft: no mic, missing model,
onnxruntime/openwakeword/sounddevice absent, or ECAPA unavailable → the listener
logs and disables itself; IRA never crashes. Everything heavy is lazy-imported so
this module loads in the lightweight (no-audio) test env.

Deps live in voice/wakeword.requirements.txt (optional extras), kept OUT of IRA's
pinned requirements.txt so they cannot disturb its resolution.

Config via env:
  IRA_WAKEWORD_ENABLED     "true" to start the listener at app startup (default OFF)
  IRA_WAKEWORD_MODEL       openWakeWord model name/path (default "hey_jarvis")
  IRA_WAKEWORD_THRESHOLD   detection score 0–1 (default 0.5)
  IRA_WAKEWORD_COOLDOWN    seconds between activations (default 2.0)
  IRA_WAKEWORD_VERIFY_SECS owner-verification window after a hit (default 1.0)
  IRA_WAKEWORD_COMMAND_SECS command capture window (default 5.0)
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import os
import time
import wave
from typing import Awaitable, Callable, Optional, Protocol

from utils.prompt_safety import check_adversarial_content

logger = logging.getLogger("ira.wakeword")

SAMPLE_RATE = 16_000              # openWakeWord + ECAPA + Whisper all expect 16 kHz mono
FRAME_SAMPLES = 1_280            # 80 ms frames @ 16 kHz
FRAME_BYTES = FRAME_SAMPLES * 2  # 16-bit


def enabled() -> bool:
    return os.getenv("IRA_WAKEWORD_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


def _secs_to_frames(secs: float) -> int:
    return max(1, int(round(secs * SAMPLE_RATE / FRAME_SAMPLES)))


def _pcm16_to_wav(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Wrap raw 16-bit mono PCM into a WAV blob (stdlib only) for transcribe_audio_bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def is_available() -> tuple[bool, str]:
    """Whether the wake-word stack can be imported. (False, reason) when it can't,
    so CI / a box without audio degrades cleanly."""
    try:
        import onnxruntime  # noqa: F401
        import openwakeword  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return False, f"openwakeword/onnxruntime not available: {exc}"
    return True, "ok"


# ── Pluggable seams (real impls lazy-import heavy deps; tests inject fakes) ───

class AudioSource(Protocol):
    def read(self) -> Optional[bytes]: ...   # one 80 ms 16-bit PCM frame, or None at end
    def close(self) -> None: ...


class Detector(Protocol):
    def score(self, frame: bytes) -> float: ...


class MicAudioSource:
    """Continuous local-microphone capture in 80 ms 16-bit frames via sounddevice."""

    def __init__(self):
        import sounddevice as sd  # lazy: PortAudio only needed when actually listening

        self._stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=FRAME_SAMPLES)
        self._stream.start()

    def read(self) -> Optional[bytes]:
        data, _overflowed = self._stream.read(FRAME_SAMPLES)
        return bytes(data)

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._stream.stop()
            self._stream.close()


class WakeWordDetector:
    """openWakeWord model wrapper — score one 80 ms frame, return the max model score."""

    def __init__(self, model: str = "hey_jarvis"):
        from openwakeword.model import Model  # lazy

        # A bare name selects a bundled pretrained model; a path loads a custom one.
        kwargs = {"wakeword_models": [model]} if model else {}
        self._model = Model(**kwargs)

    def score(self, frame: bytes) -> float:
        import numpy as np

        samples = np.frombuffer(frame, dtype=np.int16)
        scores = self._model.predict(samples)
        return float(max(scores.values())) if scores else 0.0


# ── Default IRA-backed gate / transcribe (reuse existing code; never reimplement) ──

async def _default_gate(pcm: bytes, *, session_id: str) -> bool:
    from voice.gate import gate_from_audio

    decision = await gate_from_audio(pcm, session_id=session_id)
    return bool(decision.get("is_owner"))


def _default_transcribe(wav: bytes) -> str:
    from voice.stt import transcribe_audio_bytes

    text, _lang, _conf, _pcm = transcribe_audio_bytes(wav)
    return text or ""


# ── The listener ─────────────────────────────────────────────────────────────

class WakeWordListener:
    """Continuous wake-word loop. Detect → ECAPA owner-gate → STT → feed_percept.

    Seams (detector, audio_source, gate, transcribe) are injectable so the control
    flow is testable without a mic, model, or GPU.
    """

    def __init__(
        self,
        app,
        *,
        detector: Detector,
        audio_source: AudioSource,
        gate: Optional[Callable[..., Awaitable[bool]]] = None,
        transcribe: Optional[Callable[[bytes], str]] = None,
        threshold: float = 0.5,
        cooldown: float = 2.0,
        verify_frames: int = _secs_to_frames(1.0),
        command_frames: int = _secs_to_frames(5.0),
    ):
        self.app = app
        self._detector = detector
        self._source = audio_source
        self._gate = gate or _default_gate
        self._transcribe = transcribe or _default_transcribe
        self.threshold = threshold
        self.cooldown = cooldown
        self.verify_frames = verify_frames
        self.command_frames = command_frames
        self.running = False
        # -inf (not 0.0): time.monotonic()'s reference point is arbitrary, so a
        # freshly-booted box could have monotonic() < cooldown and wrongly suppress
        # the very first activation. -inf guarantees the first wake always fires.
        self._last_fire = float("-inf")

    def stop(self) -> None:
        self.running = False

    async def run(self) -> None:
        self.running = True
        loop = asyncio.get_running_loop()
        logger.info("Wake-word listener online (threshold=%.2f).", self.threshold)
        try:
            while self.running:
                frame = await loop.run_in_executor(None, self._source.read)
                if frame is None:
                    break  # source ended
                score = await loop.run_in_executor(None, self._detector.score, frame)
                if score >= self.threshold and (time.monotonic() - self._last_fire) >= self.cooldown:
                    await self._on_wake(loop)
        except Exception as exc:  # noqa: BLE001 - never let the loop crash IRA
            logger.warning("Wake-word listener stopped on error: %s", exc)
        finally:
            with contextlib.suppress(Exception):
                self._source.close()

    async def _read_window(self, loop, n_frames: int) -> bytes:
        buf = bytearray()
        for _ in range(n_frames):
            f = await loop.run_in_executor(None, self._source.read)
            if f is None:
                break
            buf += f
        return bytes(buf)

    async def _on_wake(self, loop) -> None:
        # a) owner gate — capture a short window and verify it's the owner's voice
        verify_pcm = await self._read_window(loop, self.verify_frames)
        is_owner = await self._gate(verify_pcm, session_id="wakeword")
        if not is_owner:
            logger.info("Wake word fired but speaker is not the owner — ignoring.")
            self._last_fire = time.monotonic()
            return

        # b) capture the command and transcribe it locally
        command_pcm = await self._read_window(loop, self.command_frames)
        wav = _pcm16_to_wav(command_pcm)
        text = (await loop.run_in_executor(None, self._transcribe, wav)).strip()
        self._last_fire = time.monotonic()
        if not text:
            return

        # c) audit + inject into the brain via the existing percept seam (owner-gated)
        flags = check_adversarial_content(text)
        if flags:
            logger.warning("wakeword: adversarial patterns in command: %s", flags)
        from api.routes.brain import feed_percept

        await feed_percept(self.app, "voice", text)


# ── Lifecycle (called from main.lifespan) ────────────────────────────────────

async def start_wakeword(app) -> None:
    """Start the wake-word listener as a background task. No-op unless enabled;
    fail-soft so it can never block or crash API startup."""
    if not enabled():
        logger.info("Wake word disabled (set IRA_WAKEWORD_ENABLED=true to enable)")
        return
    try:
        ok, reason = is_available()
        if not ok:
            raise RuntimeError(reason)
        loop = asyncio.get_running_loop()
        model = os.getenv("IRA_WAKEWORD_MODEL", "hey_jarvis").strip()
        # Model load + mic open are blocking — do them off the event loop.
        detector = await loop.run_in_executor(None, lambda: WakeWordDetector(model=model))
        source = await loop.run_in_executor(None, MicAudioSource)
        listener = WakeWordListener(
            app, detector=detector, audio_source=source,
            threshold=float(os.getenv("IRA_WAKEWORD_THRESHOLD", "0.5")),
            cooldown=float(os.getenv("IRA_WAKEWORD_COOLDOWN", "2.0")),
            verify_frames=_secs_to_frames(float(os.getenv("IRA_WAKEWORD_VERIFY_SECS", "1.0"))),
            command_frames=_secs_to_frames(float(os.getenv("IRA_WAKEWORD_COMMAND_SECS", "5.0"))),
        )
        app.state.wakeword = listener
        task = asyncio.create_task(listener.run())
        task.add_done_callback(
            lambda t: t.cancelled() or (t.exception() and logger.warning(
                "Wake-word task ended: %s", t.exception())))
        app.state.wakeword_task = task
        logger.info("Wake word online (model=%s)", model)
    except Exception as exc:  # noqa: BLE001 - never block startup
        logger.warning("Wake word failed to start (non-fatal): %s", exc)
        app.state.wakeword = None


async def stop_wakeword(app) -> None:
    listener = getattr(app.state, "wakeword", None)
    if listener is not None:
        listener.stop()
    task = getattr(app.state, "wakeword_task", None)
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        app.state.wakeword_task = None
    app.state.wakeword = None


__all__ = [
    "enabled", "is_available", "start_wakeword", "stop_wakeword",
    "WakeWordListener", "WakeWordDetector", "MicAudioSource",
    "SAMPLE_RATE", "FRAME_SAMPLES",
]
