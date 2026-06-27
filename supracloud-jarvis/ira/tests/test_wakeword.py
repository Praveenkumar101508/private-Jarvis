"""Tests for the owner-gated wake-word trigger (voice/wakeword.py).

The real stack (openwakeword/onnxruntime/sounddevice/ECAPA) needs a mic + models, so
these cover the control flow that CAN run in CI with everything mocked: the flag, the
availability check, the PCM→WAV helper, and the detect→owner-gate→STT→feed_percept
pipeline (including the owner gate blocking non-owners, cooldown, and empty transcripts).
"""
from __future__ import annotations

import io
import types
import wave

import pytest

from voice.wakeword import (
    WakeWordListener,
    _pcm16_to_wav,
    _secs_to_frames,
    enabled,
    is_available,
    start_wakeword,
)

SILENCE = b"\x00" * 2560   # one 80 ms frame
TRIGGER = b"\x11" * 2560   # a distinct frame the fake detector fires on


# ── Flag, availability, helpers ──────────────────────────────────────────────

def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("IRA_WAKEWORD_ENABLED", raising=False)
    assert enabled() is False


def test_enabled_reads_env(monkeypatch):
    monkeypatch.setenv("IRA_WAKEWORD_ENABLED", "true")
    assert enabled() is True
    monkeypatch.setenv("IRA_WAKEWORD_ENABLED", "0")
    assert enabled() is False


def test_is_available_false_without_deps():
    # openwakeword/onnxruntime are optional extras, never in test deps → unavailable.
    ok, reason = is_available()
    assert ok is False and "openwakeword" in reason.lower()


def test_pcm16_to_wav_header():
    pcm = b"\x00\x00" * 1600   # 100 ms @ 16 kHz
    wav = _pcm16_to_wav(pcm, 16_000)
    assert wav[:4] == b"RIFF"
    with wave.open(io.BytesIO(wav)) as wf:
        assert wf.getframerate() == 16_000
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getnframes() == 1600


def test_secs_to_frames():
    assert _secs_to_frames(0.0) == 1                       # never zero
    assert _secs_to_frames(5.0) > _secs_to_frames(1.0)     # scales with duration


# ── Pipeline fakes ───────────────────────────────────────────────────────────

class _FakeSource:
    def __init__(self, frames):
        self._frames = list(frames)
        self.closed = False

    def read(self):
        return self._frames.pop(0) if self._frames else None

    def close(self):
        self.closed = True


class _FakeDetector:
    def __init__(self, trigger=TRIGGER):
        self._trigger = trigger

    def score(self, frame):
        return 0.9 if frame == self._trigger else 0.0


class _FakeBrain:
    def __init__(self):
        self.perceived = []

    async def perceive(self, source, text):
        self.perceived.append((source, text))


def _app_with_brain():
    return types.SimpleNamespace(state=types.SimpleNamespace(brain=_FakeBrain()))


async def _ok_gate(pcm, *, session_id):
    return True


async def _deny_gate(pcm, *, session_id):
    return False


# ── Detect → owner-gate → STT → feed_percept ─────────────────────────────────

async def test_owner_command_is_injected_as_voice_percept():
    app = _app_with_brain()
    src = _FakeSource([SILENCE, TRIGGER, SILENCE, SILENCE])  # trigger, then verify+command frames
    listener = WakeWordListener(
        app, detector=_FakeDetector(), audio_source=src,
        gate=_ok_gate, transcribe=lambda wav: "turn on the lights",
        threshold=0.5, cooldown=2.0, verify_frames=1, command_frames=1,
    )
    await listener.run()
    assert app.state.brain.perceived == [("voice", "turn on the lights")]
    assert src.closed is True


async def test_non_owner_is_ignored():
    app = _app_with_brain()
    src = _FakeSource([SILENCE, TRIGGER, SILENCE])
    listener = WakeWordListener(
        app, detector=_FakeDetector(), audio_source=src,
        gate=_deny_gate, transcribe=lambda wav: "should never run",
        threshold=0.5, cooldown=2.0, verify_frames=1, command_frames=1,
    )
    await listener.run()
    assert app.state.brain.perceived == []   # owner gate blocked activation


async def test_empty_transcript_is_not_injected():
    app = _app_with_brain()
    src = _FakeSource([TRIGGER, SILENCE, SILENCE])
    listener = WakeWordListener(
        app, detector=_FakeDetector(), audio_source=src,
        gate=_ok_gate, transcribe=lambda wav: "   ",
        threshold=0.5, cooldown=2.0, verify_frames=1, command_frames=1,
    )
    await listener.run()
    assert app.state.brain.perceived == []


async def test_cooldown_debounces_rapid_triggers():
    app = _app_with_brain()
    # two triggers back-to-back; a long cooldown must suppress the second activation
    src = _FakeSource([TRIGGER, SILENCE, SILENCE, TRIGGER, SILENCE, SILENCE])
    listener = WakeWordListener(
        app, detector=_FakeDetector(), audio_source=src,
        gate=_ok_gate, transcribe=lambda wav: "hello",
        threshold=0.5, cooldown=100.0, verify_frames=1, command_frames=1,
    )
    await listener.run()
    assert app.state.brain.perceived == [("voice", "hello")]   # exactly one


# ── Lifecycle ────────────────────────────────────────────────────────────────

async def test_start_wakeword_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("IRA_WAKEWORD_ENABLED", raising=False)
    app = types.SimpleNamespace(state=types.SimpleNamespace())
    await start_wakeword(app)
    assert getattr(app.state, "wakeword", None) is None


async def test_start_wakeword_failsoft_when_unavailable(monkeypatch):
    # enabled, but openwakeword/onnxruntime absent → disables cleanly, no crash
    monkeypatch.setenv("IRA_WAKEWORD_ENABLED", "true")
    app = types.SimpleNamespace(state=types.SimpleNamespace())
    await start_wakeword(app)
    assert getattr(app.state, "wakeword", None) is None
