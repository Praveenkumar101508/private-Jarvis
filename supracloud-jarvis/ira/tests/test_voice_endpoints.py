"""Phase 6 — browser-native voice endpoints + helpers.

Covers (all runnable in the lightweight CI env — no livekit / supertonic /
faster-whisper needed, the engines are stubbed):
  * POST /voice/say returns a valid WAV (RIFF/WAVE header, audio/wav).
  * synthesize_wav's Indic language fallback (ta/te -> na, hi -> hi).
  * the TTS engine factory selects supertonic vs kokoro by IRA_VOICE_ENGINE.
  * POST /voice/transcribe returns {text, is_owner} (DEV_MODE owner + fail-closed).
"""
import os

# Settings require these; prime them before importing config-backed code.
for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

import types

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _voice_app() -> FastAPI:
    """A bare app mounting just the voice router, with auth overridden."""
    from api.routes.voice import router
    from api.middleware.auth import require_auth

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: "admin"
    return app


# ── POST /voice/say ───────────────────────────────────────────────────────────

def test_say_returns_valid_wav(monkeypatch):
    import voice.tts_supertonic as ts

    def _fake_synth(text, voice="F1", lang="en", steps=None):
        return ts._encode_wav(np.zeros(2205, dtype=np.float32), 44_100)

    monkeypatch.setattr(ts, "synthesize_wav", _fake_synth)
    client = TestClient(_voice_app())
    r = client.post("/api/v1/voice/say", json={"text": "Hello, I am IRA."})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    assert r.content[:4] == b"RIFF" and r.content[8:12] == b"WAVE"


def test_say_rejects_empty_text():
    client = TestClient(_voice_app())
    r = client.post("/api/v1/voice/say", json={"text": "   "})
    assert r.status_code == 400


# ── synthesize_wav language fallback + WAV encoder ────────────────────────────

def test_supertonic_indic_fallback():
    from voice.tts_supertonic import _supertonic_lang

    assert _supertonic_lang("ta") == "na"   # Tamil — unsupported -> language-agnostic
    assert _supertonic_lang("te") == "na"   # Telugu — unsupported -> na
    assert _supertonic_lang("hi") == "hi"   # Hindi — natively supported, stays hi
    assert _supertonic_lang("en") == "en"


def test_encode_wav_header():
    from voice.tts_supertonic import _encode_wav

    wav = _encode_wav(np.zeros(441, dtype=np.float32), 44_100)
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"


# ── TTS engine factory selection ──────────────────────────────────────────────

class _FakeEngine:
    def __init__(self, voice, speed: float = 1.05):
        self.voice = voice
        self.speed = speed


def test_factory_selects_supertonic(monkeypatch):
    import voice.tts_supertonic as sup
    import voice.tts_factory as factory

    monkeypatch.setenv("IRA_VOICE_ENGINE", "supertonic")
    monkeypatch.setattr(sup, "IRASupertonicTTS", _FakeEngine)
    engine = factory.make_tts("F1", speed=1.05)
    assert isinstance(engine, _FakeEngine) and engine.voice == "F1"


def test_factory_defaults_to_kokoro(monkeypatch):
    import voice.tts as ttsmod
    import voice.tts_factory as factory

    monkeypatch.delenv("IRA_VOICE_ENGINE", raising=False)
    monkeypatch.setattr(ttsmod, "IRAKokoroTTS", _FakeEngine)
    engine = factory.make_tts("af_bella")
    assert isinstance(engine, _FakeEngine) and engine.voice == "af_bella"


def test_factory_falls_back_to_kokoro_on_supertonic_error(monkeypatch):
    import voice.tts as ttsmod
    import voice.tts_supertonic as sup
    import voice.tts_factory as factory

    def _boom(*a, **k):
        raise RuntimeError("supertonic model missing")

    monkeypatch.setenv("IRA_VOICE_ENGINE", "supertonic")
    monkeypatch.setattr(sup, "IRASupertonicTTS", _boom)
    monkeypatch.setattr(ttsmod, "IRAKokoroTTS", _FakeEngine)
    engine = factory.make_tts("af_bella")
    assert isinstance(engine, _FakeEngine)   # gracefully fell back to Kokoro


# ── POST /voice/transcribe ────────────────────────────────────────────────────

def test_transcribe_devmode_is_owner_true(monkeypatch):
    import voice.stt as stt
    import api.routes.voice as vroute

    monkeypatch.setattr(
        stt, "transcribe_audio_bytes",
        lambda blob, *a, **k: ("what time is it", "en", 0.98, b"\x00\x00" * 1600),
    )
    monkeypatch.setattr(vroute, "get_settings", lambda: types.SimpleNamespace(dev_mode=True))
    client = TestClient(_voice_app())
    r = client.post("/api/v1/voice/transcribe", files={"audio": ("u.webm", b"webmblob", "audio/webm")})
    assert r.status_code == 200
    assert r.json() == {"text": "what time is it", "is_owner": True}


def test_transcribe_nonowner_fails_closed(monkeypatch):
    import voice.stt as stt
    import voice.gate as gate
    import api.routes.voice as vroute

    monkeypatch.setattr(
        stt, "transcribe_audio_bytes",
        lambda blob, *a, **k: ("show me the logs", "en", 0.9, b"\x00\x00" * 1600),
    )
    monkeypatch.setattr(vroute, "get_settings", lambda: types.SimpleNamespace(dev_mode=False))

    async def _nonowner(pcm, **k):
        return {"is_owner": False, "clearance": "public", "restricted_allowed": False}

    monkeypatch.setattr(gate, "gate_from_audio", _nonowner)
    client = TestClient(_voice_app())
    r = client.post("/api/v1/voice/transcribe", files={"audio": ("u.webm", b"x", "audio/webm")})
    assert r.status_code == 200
    assert r.json()["text"] == "show me the logs"
    assert r.json()["is_owner"] is False


def test_transcribe_rejects_empty_audio():
    client = TestClient(_voice_app())
    r = client.post("/api/v1/voice/transcribe", files={"audio": ("e.webm", b"", "audio/webm")})
    assert r.status_code == 400
