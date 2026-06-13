"""
voice/tts_factory.py — pick the IRA TTS engine from one env flag.

Mirrors the IRA_USE_HERMES feature-flag pattern: the default is the existing
engine (safe), and flipping one env var swaps it. Nothing else in voice/agent.py
needs to know which engine is live.

  IRA_VOICE_ENGINE = "kokoro"      (default — current behaviour, unchanged)
                   = "supertonic"  (on-device Supertonic-3, female default)

Voice name and speed are passed through unchanged (IRA_VOICE picks the voice;
for Supertonic that's F1–F5 female / M1–M5 male, for Kokoro af_bella/af_heart).
"""

from __future__ import annotations

import logging
import os

from livekit.agents import tts

logger = logging.getLogger("ira.tts.factory")


def make_tts(voice: str, speed: float = 1.05) -> tts.TTS:
    """Return the configured TTS engine. Falls back to Kokoro on any import error
    so a missing Supertonic install can never take the voice agent down."""
    engine = os.getenv("IRA_VOICE_ENGINE", "kokoro").strip().lower()

    if engine == "supertonic":
        try:
            from voice.tts_supertonic import IRASupertonicTTS, DEFAULT_VOICE
            # If IRA_VOICE is still a Kokoro name, use Supertonic's female default.
            v = voice if voice and voice.upper()[:1] in ("F", "M") else DEFAULT_VOICE
            logger.info(f"TTS engine: Supertonic (voice={v})")
            return IRASupertonicTTS(voice=v, speed=speed)
        except Exception as e:
            logger.error(f"Supertonic engine unavailable ({e}); falling back to Kokoro.")

    from voice.tts import IRAKokoroTTS
    logger.info(f"TTS engine: Kokoro (voice={voice})")
    return IRAKokoroTTS(voice=voice, speed=speed)
