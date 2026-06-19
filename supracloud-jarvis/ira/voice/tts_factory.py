"""
voice/tts_factory.py — pick the IRA TTS engine from one env flag.

Mirrors the IRA_USE_CORTEX feature-flag pattern: the default is the existing
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

# `tts` is only used for the `-> tts.TTS` return annotation (a string under
# `from __future__ import annotations`). Import it softly so this module loads on a
# host without livekit; make_tts still returns a real engine when livekit is present.
try:
    from livekit.agents import tts
except Exception:  # pragma: no cover - only on hosts without livekit-agents
    tts = None

logger = logging.getLogger("ira.tts.factory")


def make_tts(voice: str, speed: float = 1.05) -> tts.TTS:
    """Return the configured TTS engine. Falls back to Kokoro on any import error
    so a missing Supertonic install can never take the voice agent down."""
    engine = os.getenv("IRA_VOICE_ENGINE", "kokoro").strip().lower()

    if engine == "omnivoice":
        try:
            from voice.tts_omnivoice import IRAOmniVoiceTTS, is_available
            ok, reason = is_available()
            if not ok:
                raise RuntimeError(reason)
            logger.info("TTS engine: OmniVoice (sidecar)")
            return IRAOmniVoiceTTS(voice=voice, speed=speed)
        except Exception as e:
            logger.error(f"OmniVoice engine unavailable ({e}); falling back to Supertonic/Kokoro.")

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


# Languages handled by the native Indic engine; everything else uses Supertonic.
_INDIC_LANGS = frozenset({"ta", "te", "kn", "ml"})


def _say_engine() -> str:
    """Selected engine for the HTTP /voice/say path (mirrors IRA_VOICE_ENGINE)."""
    return os.getenv("IRA_VOICE_ENGINE", "kokoro").strip().lower()


def synthesize_say(text: str, *, lang: str = "en", voice: str | None = None,
                   steps: int | None = None) -> bytes:
    """Pick the TTS engine by language and return a 44.1 kHz WAV (the HTTP /voice/say
    path). When IRA_VOICE_ENGINE=omnivoice, OmniVoice (600+ langs) handles everything,
    failing soft to the logic below. Otherwise: Tamil/Telugu/Kannada/Malayalam route to
    the native Indic engine (fail soft to Supertonic's 'na'); everything else — incl.
    Hindi and Supertonic's other 30 languages — uses Supertonic."""
    if _say_engine() == "omnivoice":
        try:
            from voice.tts_omnivoice import synthesize_wav_omnivoice
            wav = synthesize_wav_omnivoice(text, lang=lang, voice=voice, steps=steps)
            if wav:
                return wav
            logger.warning("OmniVoice produced no audio; falling back to Supertonic/Indic.")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"OmniVoice TTS error ({e}); falling back to Supertonic/Indic.")

    code = (lang or "en").lower().split("-")[0]
    if code in _INDIC_LANGS:
        try:
            from voice.tts_indic import synthesize_wav_indic
            wav = synthesize_wav_indic(text, lang=code)
            if wav:
                return wav
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Indic TTS error ({e}); falling back to Supertonic 'na'.")
    from voice.tts_supertonic import synthesize_wav, DEFAULT_VOICE
    return synthesize_wav(text, voice or DEFAULT_VOICE, code, steps)
