"""Tests for local voice output (voice/voice_output.py).

The real path needs a TTS engine + audio device, so these cover the control flow
that runs in CI with everything mocked: the flag, on_speak → synth → playback,
affect instruct/speed passthrough, serialization, fail-soft, queue-drop, and the
start/stop lifecycle (subscribe/unsubscribe).
"""
from __future__ import annotations

import types

import pytest

from voice.voice_output import VoiceOutput, output_mode, start_voice_output, stop_voice_output


class _FakeSynth:
    def __init__(self):
        self.calls = []

    def synth(self, text, *, instruct=None, speed=None):
        self.calls.append((text, instruct, speed))
        return b"WAV:" + text.encode()


class _FakeSink:
    def __init__(self):
        self.played = []

    def play(self, wav):
        self.played.append(wav)


# ── Flag ──────────────────────────────────────────────────────────────────────

def test_output_mode_default_none(monkeypatch):
    monkeypatch.delenv("IRA_VOICE_OUTPUT", raising=False)
    assert output_mode() == "none"


def test_output_mode_local(monkeypatch):
    monkeypatch.setenv("IRA_VOICE_OUTPUT", "local")
    assert output_mode() == "local"


# ── on_speak → synth → playback ──────────────────────────────────────────────

async def test_routes_synth_to_playback_in_order():
    synth, sink = _FakeSynth(), _FakeSink()
    vo = VoiceOutput(synth=synth.synth, sink=sink)
    vo.handler("hello")
    vo.handler("world")
    vo._q.put_nowait(None)            # sentinel ends the worker
    await vo.run()
    assert sink.played == [b"WAV:hello", b"WAV:world"]          # serialized, in order
    assert synth.calls == [("hello", None, None), ("world", None, None)]


async def test_affect_style_passed_to_synth():
    synth = _FakeSynth()
    vo = VoiceOutput(synth=synth.synth, sink=_FakeSink(),
                     voice_style=lambda: {"instruct": "warm, gentle", "speed": 0.9})
    vo.handler("hi")
    vo._q.put_nowait(None)
    await vo.run()
    assert synth.calls == [("hi", "warm, gentle", 0.9)]


async def test_empty_audio_is_not_played():
    sink = _FakeSink()
    vo = VoiceOutput(synth=lambda text, *, instruct=None, speed=None: b"", sink=sink)
    vo.handler("x")
    vo._q.put_nowait(None)
    await vo.run()
    assert sink.played == []


async def test_failsoft_on_sink_error_continues():
    class _FlakySink:
        def __init__(self):
            self.played = []
            self._first = True

        def play(self, wav):
            if self._first:
                self._first = False
                raise RuntimeError("no audio device")
            self.played.append(wav)

    sink = _FlakySink()
    vo = VoiceOutput(synth=lambda text, *, instruct=None, speed=None: b"W:" + text.encode(), sink=sink)
    vo.handler("a")
    vo.handler("b")
    vo._q.put_nowait(None)
    await vo.run()
    assert sink.played == [b"W:b"]    # first raised, worker recovered and played the second


def test_handler_drops_when_queue_full():
    vo = VoiceOutput(synth=_FakeSynth().synth, sink=_FakeSink(), max_queue=2)
    vo.handler("1")
    vo.handler("2")
    vo.handler("3")                    # dropped — must not raise
    assert vo._q.qsize() == 2


def test_handler_ignores_empty_text():
    vo = VoiceOutput(synth=_FakeSynth().synth, sink=_FakeSink())
    vo.handler("   ")
    assert vo._q.qsize() == 0


# ── Lifecycle ────────────────────────────────────────────────────────────────

class _FakeBrain:
    def __init__(self):
        self.subs = []
        self.affect = None

    def on_speak(self, cb):
        self.subs.append(cb)

    def off_speak(self, cb):
        if cb in self.subs:
            self.subs.remove(cb)


async def test_start_voice_output_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("IRA_VOICE_OUTPUT", raising=False)
    app = types.SimpleNamespace(state=types.SimpleNamespace())
    await start_voice_output(app, _FakeBrain())
    assert getattr(app.state, "voice_output", None) is None


async def test_start_voice_output_noop_without_brain(monkeypatch):
    monkeypatch.setenv("IRA_VOICE_OUTPUT", "local")
    app = types.SimpleNamespace(state=types.SimpleNamespace())
    await start_voice_output(app, None)
    assert getattr(app.state, "voice_output", None) is None


async def test_start_and_stop_voice_output_local(monkeypatch):
    monkeypatch.setenv("IRA_VOICE_OUTPUT", "local")
    brain = _FakeBrain()
    app = types.SimpleNamespace(state=types.SimpleNamespace(brain=brain))
    await start_voice_output(app, brain)
    assert app.state.voice_output is not None
    assert len(brain.subs) == 1          # subscribed to on_speak (additive to WS frames)
    await stop_voice_output(app)
    assert app.state.voice_output is None
    assert brain.subs == []              # unsubscribed cleanly
