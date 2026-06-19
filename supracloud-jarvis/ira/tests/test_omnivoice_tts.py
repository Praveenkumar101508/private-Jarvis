"""Tests for the OmniVoice TTS sidecar integration.

The real synthesis path is GPU-only (separate venv with CUDA torch + transformers>=5),
so it cannot run in CI. These cover the IRA-side contract that CAN run without
torch/omnivoice/livekit/numpy: the wire protocol, availability gating, the subprocess
client against a fake process, fail-soft behaviour, and engine selection/fallback in
tts_factory. A numpy-only resample/encode check is included behind importorskip.
"""
from __future__ import annotations

import io
import sys
import types

import pytest

from voice.omnivoice_protocol import read_message, write_message
from voice import tts_omnivoice as ov


# ── Wire protocol ────────────────────────────────────────────────────────────

def test_protocol_roundtrip_header_and_payload():
    buf = io.BytesIO()
    write_message(buf, {"op": "synth", "text": "hi"}, b"\x00\x01\x02\n\x03")
    buf.seek(0)
    header, payload = read_message(buf)
    assert header == {"op": "synth", "text": "hi"}
    assert payload == b"\x00\x01\x02\n\x03"   # payload may contain newlines


def test_protocol_empty_payload():
    buf = io.BytesIO()
    write_message(buf, {"op": "ping"})
    buf.seek(0)
    assert read_message(buf) == ({"op": "ping"}, b"")


def test_protocol_sequential_messages_then_eof():
    buf = io.BytesIO()
    write_message(buf, {"i": 1}, b"a")
    write_message(buf, {"i": 2}, b"bb")
    buf.seek(0)
    assert read_message(buf) == ({"i": 1}, b"a")
    assert read_message(buf) == ({"i": 2}, b"bb")
    assert read_message(buf) is None  # clean EOF


def test_protocol_truncated_frame_returns_none():
    buf = io.BytesIO(b"\x00\x00\x00\x10short")  # claims 16 bytes, supplies 5
    assert read_message(buf) is None


# ── Availability gating ──────────────────────────────────────────────────────

def test_is_available_false_without_python(monkeypatch):
    monkeypatch.delenv("IRA_OMNIVOICE_PYTHON", raising=False)
    ok, reason = ov.is_available()
    assert ok is False and "IRA_OMNIVOICE_PYTHON" in reason


def test_is_available_false_when_python_missing(monkeypatch):
    monkeypatch.setenv("IRA_OMNIVOICE_PYTHON", "/no/such/python")
    ok, reason = ov.is_available()
    assert ok is False and "not found" in reason


def test_is_available_true_with_real_python(monkeypatch):
    monkeypatch.setenv("IRA_OMNIVOICE_PYTHON", sys.executable)
    ok, reason = ov.is_available()
    assert ok is True and reason == "ok"


# ── Sidecar client against a fake process ────────────────────────────────────

class _FakeProc:
    """Fake Popen: stdin captures writes, stdout serves preloaded response frames."""

    def __init__(self, response_frames: bytes, alive: bool = True):
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO(response_frames)
        self._alive = alive
        self.killed = False

    def poll(self):
        return None if self._alive else 0

    def kill(self):
        self.killed = True


def _framed(header: dict, payload: bytes = b"") -> bytes:
    b = io.BytesIO()
    write_message(b, header, payload)
    return b.getvalue()


def _client_with(proc) -> ov.OmniVoiceSidecar:
    c = ov.OmniVoiceSidecar("py", model="m", device="cpu", dtype="float16", cwd=".")
    c._proc = proc
    return c


def test_synth_returns_pcm_and_sends_request():
    pcm = b"\x01\x02\x03\x04" * 4
    proc = _FakeProc(_framed({"ok": True, "sr": 24000, "format": "f32le"}, pcm))
    client = _client_with(proc)
    out = client.synth("hello", language="en", num_step=16)
    assert out == pcm
    proc.stdin.seek(0)
    req_header, _ = read_message(proc.stdin)
    assert req_header["op"] == "synth"
    assert req_header["text"] == "hello"
    assert req_header["language"] == "en"
    assert req_header["num_step"] == 16


def test_synth_error_header_returns_empty():
    proc = _FakeProc(_framed({"ok": False, "error": "boom"}))
    assert _client_with(proc).synth("hello") == b""


def test_synth_dead_process_fails_soft(monkeypatch):
    proc = _FakeProc(b"", alive=False)            # poll() != None → respawn attempted
    client = _client_with(proc)
    monkeypatch.setattr(client, "_spawn", lambda: None)  # respawn no-op leaves it dead
    assert client.synth("hello") == b""


def test_ping_ok():
    proc = _FakeProc(_framed({"ok": True, "pong": True}))
    assert _client_with(proc).ping() is True


# ── _get_sidecar + synthesize_wav_omnivoice fail-soft ────────────────────────

def test_get_sidecar_none_when_unavailable(monkeypatch):
    monkeypatch.delenv("IRA_OMNIVOICE_PYTHON", raising=False)
    ov._sidecar = None
    assert ov._get_sidecar() is None


def test_synthesize_wav_failsoft_without_sidecar(monkeypatch):
    monkeypatch.setattr(ov, "_get_sidecar", lambda: None)
    assert ov.synthesize_wav_omnivoice("hi", lang="en") == b""


def test_synthesize_wav_failsoft_on_empty_pcm(monkeypatch):
    class _C:
        def synth(self, *a, **k):
            return b""
    monkeypatch.setattr(ov, "_get_sidecar", lambda: _C())
    assert ov.synthesize_wav_omnivoice("hi", lang="en") == b""


# ── Engine selection + fallback in tts_factory ───────────────────────────────

def test_say_engine_selection(monkeypatch):
    from voice import tts_factory
    monkeypatch.setenv("IRA_VOICE_ENGINE", "omnivoice")
    assert tts_factory._say_engine() == "omnivoice"
    monkeypatch.delenv("IRA_VOICE_ENGINE", raising=False)
    assert tts_factory._say_engine() == "kokoro"


def test_synthesize_say_uses_omnivoice_when_selected(monkeypatch):
    from voice import tts_factory
    monkeypatch.setenv("IRA_VOICE_ENGINE", "omnivoice")
    monkeypatch.setattr(
        "voice.tts_omnivoice.synthesize_wav_omnivoice",
        lambda text, lang="en", voice=None, steps=None, instruct=None, speed=None: b"OMNIWAV",
    )
    assert tts_factory.synthesize_say("hello", lang="en") == b"OMNIWAV"


def test_synthesize_say_falls_back_when_omnivoice_empty(monkeypatch):
    from voice import tts_factory
    monkeypatch.setenv("IRA_VOICE_ENGINE", "omnivoice")
    monkeypatch.setattr("voice.tts_omnivoice.synthesize_wav_omnivoice", lambda *a, **k: b"")
    # Stub the Supertonic fallback so the test needs no numpy/supertonic.
    fake_st = types.ModuleType("voice.tts_supertonic")
    fake_st.synthesize_wav = lambda text, voice, code, steps: b"SUPERWAV"
    fake_st.DEFAULT_VOICE = "F1"
    monkeypatch.setitem(sys.modules, "voice.tts_supertonic", fake_st)
    assert tts_factory.synthesize_say("hello", lang="en") == b"SUPERWAV"


# ── Resample + WAV encode (numpy only; skipped where numpy absent) ────────────

def test_pcm_to_wav_resamples_and_encodes():
    np = pytest.importorskip("numpy")
    import wave

    samples = np.full(240, 0.5, dtype="<f4")        # 10 ms @ 24 kHz
    wav = ov._pcm_to_wav(samples.tobytes(), 24_000, 44_100)
    assert wav[:4] == b"RIFF"
    with wave.open(io.BytesIO(wav)) as wf:
        assert wf.getframerate() == 44_100
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert abs(wf.getnframes() - 441) <= 2     # 240 * 44100/24000 ≈ 441
