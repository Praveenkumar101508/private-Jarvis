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
