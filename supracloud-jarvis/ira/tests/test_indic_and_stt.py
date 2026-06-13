"""Phase 4 — multilingual TTS routing + STT robustness.

The Indic engine (torch/parler) isn't in CI, so it's stubbed / exercised via its
fail-soft path; Whisper is stubbed with a fake model.
"""
import os

for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

import numpy as np


# ── TTS language routing ──────────────────────────────────────────────────────

def _wav(n: int) -> bytes:
    from voice.tts_supertonic import _encode_wav
    return _encode_wav(np.zeros(n, dtype=np.float32), 44_100)


def test_say_routes_tamil_to_indic(monkeypatch):
    import voice.tts_indic as indic
    import voice.tts_factory as factory

    indic_wav = _wav(441)
    monkeypatch.setattr(indic, "synthesize_wav_indic", lambda text, lang="ta": indic_wav)
    out = factory.synthesize_say("வணக்கம்", lang="ta")
    assert out == indic_wav  # native Indic engine was used


def test_say_routes_english_to_supertonic(monkeypatch):
    import voice.tts_supertonic as sup
    import voice.tts_factory as factory

    sup_wav = _wav(882)
    monkeypatch.setattr(sup, "synthesize_wav", lambda text, voice="F1", lang="en", steps=None: sup_wav)
    out = factory.synthesize_say("hello", lang="en")
    assert out == sup_wav


def test_say_indic_falls_back_to_supertonic_when_unavailable(monkeypatch):
    import voice.tts_indic as indic
    import voice.tts_supertonic as sup
    import voice.tts_factory as factory

    monkeypatch.setattr(indic, "synthesize_wav_indic", lambda text, lang="ta": b"")  # engine missing
    sup_wav = _wav(441)
    monkeypatch.setattr(sup, "synthesize_wav", lambda text, voice="F1", lang="ta", steps=None: sup_wav)
    out = factory.synthesize_say("வணக்கம்", lang="ta")
    assert out == sup_wav  # gracefully fell back to Supertonic 'na'


def test_indic_engine_unavailable_returns_empty():
    # torch/parler aren't installed in CI -> fail-soft to b"" (caller falls back).
    import voice.tts_indic as indic
    assert indic.synthesize_wav_indic("வணக்கம்", "ta") == b""


# ── STT robustness ────────────────────────────────────────────────────────────

def test_stt_vad_and_model_defaults():
    import voice.stt as stt
    # min-silence is generous so utterances aren't clipped on a brief pause.
    assert stt._VAD_MIN_SILENCE_MS >= 500
    assert stt.DEFAULT_HTTP_WHISPER_MODEL  # configurable, non-empty


def test_transcribe_sync_uses_vad_config_and_autodetect():
    import voice.stt as stt

    captured: dict = {}

    class _FakeInfo:
        language = "en"
        language_probability = 0.91

    class _FakeModel:
        def transcribe(self, audio, **kw):
            captured.update(kw)
            return ([], _FakeInfo())

    text, lang, conf = stt._transcribe_sync(np.zeros(1600, dtype=np.float32), _FakeModel(), None)
    assert captured["language"] is None  # auto-detect enabled
    assert captured["vad_filter"] is True
    assert captured["vad_parameters"]["min_silence_duration_ms"] == stt._VAD_MIN_SILENCE_MS
    assert lang == "en" and conf == 0.91
