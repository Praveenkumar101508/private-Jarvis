"""Prompt 4.6 — voice package import-smoke.

Imports every voice module so a broken dependency / API mismatch is caught
automatically (this is why the invalid livekit-agents pin slipped through before).

The heavy voice deps (livekit, torch, speechbrain) aren't installed in the
lightweight CI/unit env, so this skips there and runs for real in the voice
image / on the Shadow box where they ARE installed.
"""
import importlib

import pytest


def test_voice_package_imports_cleanly():
    pytest.importorskip("livekit", reason="voice deps not installed (Shadow/voice-image only)")
    pytest.importorskip("livekit.agents", reason="livekit-agents not installed")

    for module in ("voice.stt", "voice.tts", "voice.agent", "voice.biometrics",
                   "voice.gate", "voice.challenge", "voice.language"):
        importlib.import_module(module)


def test_pure_voice_modules_import_without_livekit():
    # gate/challenge have no heavy deps and must always import.
    importlib.import_module("voice.gate")
    importlib.import_module("voice.challenge")


def test_voice_plugins_satisfy_livekit_api():
    """Validate the plugins against the REAL livekit-agents SDK by *instantiating*
    them — catches an API mismatch (wrong base class, unimplemented abstract method,
    bad ChatChunk/ChoiceDelta shape), not just an import error. faster_whisper is
    stubbed if the ML deps aren't present, so this also runs in a livekit-only lane.

    (Confirmed against livekit-agents 1.5.17: STT/TTS/LLM signatures, ChatChunk(delta=
    ChoiceDelta(...)), AudioEmitter, and _recognize_impl/_run all match.)
    """
    pytest.importorskip("livekit.agents", reason="livekit-agents not installed")

    import sys
    import types
    if "faster_whisper" not in sys.modules:
        try:
            import faster_whisper  # noqa: F401
        except Exception:
            _m = types.ModuleType("faster_whisper")
            _m.WhisperModel = object
            sys.modules["faster_whisper"] = _m

    from livekit.agents import llm
    from voice.stt import IRAFasterWhisperSTT
    from voice.tts import IRAKokoroTTS
    from voice.agent import IRALLMAdapter

    stt_plugin = IRAFasterWhisperSTT(model_size="small")
    assert stt_plugin.capabilities.streaming is False         # non-streaming recognize path

    tts_plugin = IRAKokoroTTS()
    assert tts_plugin.sample_rate == 48_000 and tts_plugin.num_channels == 1

    # The 1.x streaming shape the adapter emits per token.
    chunk = llm.ChatChunk(id="x", delta=llm.ChoiceDelta(role="assistant", content="hi"))
    assert chunk.delta.content == "hi"

    adapter = IRALLMAdapter(session_id="s1", stt=stt_plugin)
    assert isinstance(adapter, llm.LLM)
