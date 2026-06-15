"""
voice/tts_indic.py — native Indic TTS for Tamil / Telugu / Kannada / Malayalam.

These four are OUTSIDE Supertonic's 31-language set (Supertonic reads them with its
language-agnostic 'na' fallback — intelligible, not native). This adapter uses a
native Indic engine (default IndicParler-TTS / ai4bharat) so they're spoken properly.

Everything is SOFT + lazy + fail-soft: if the engine/model isn't installed,
synthesize_wav_indic() returns b"" and the caller (tts_factory.synthesize_say) falls
back to Supertonic 'na'. The model runs on-device (sovereign); on a 20GB GPU it may
contend with the chat/coder models — a model-swap delay is acceptable.

Env:
  IRA_INDIC_TTS_ENGINE  "indic-parler" (default) | "none" (disable)
  IRA_INDIC_TTS_MODEL   HF id / local path (default ai4bharat/indic-parler-tts)
  IRA_INDIC_TTS_VOICE   voice-description prompt (default a clear female voice)
"""
from __future__ import annotations

import logging
import os
import threading

import numpy as np

from voice.tts_supertonic import _encode_wav  # shared WAV encoder (no heavy deps)

logger = logging.getLogger("ira.tts.indic")

# The languages this engine owns; everything else stays on Supertonic.
INDIC_LANGS = frozenset({"ta", "te", "kn", "ml"})

_ENGINE = os.getenv("IRA_INDIC_TTS_ENGINE", "indic-parler").strip().lower()
_MODEL = os.getenv("IRA_INDIC_TTS_MODEL", "ai4bharat/indic-parler-tts").strip()
_VOICE_DESC = os.getenv(
    "IRA_INDIC_TTS_VOICE",
    "A female speaker delivers clear, natural speech in a calm, professional tone.",
).strip()

# Thread-safe singleton (same pattern as Supertonic / Whisper).
_model = None
_tokenizer = None
_desc_tokenizer = None
_sr = 44_100
_loaded = False
_lock = threading.Lock()


def _load() -> bool:
    """Lazily load the Indic TTS model once. Returns True if it's ready."""
    global _model, _tokenizer, _desc_tokenizer, _sr, _loaded
    if _loaded:
        return _model is not None
    with _lock:
        if _loaded:
            return _model is not None
        if _ENGINE in ("", "none", "off"):
            _loaded = True
            return False
        try:
            import torch  # noqa: F401
            from parler_tts import ParlerTTSForConditionalGeneration
            from transformers import AutoTokenizer

            logger.info(f"Loading Indic TTS '{_MODEL}'...")
            model = ParlerTTSForConditionalGeneration.from_pretrained(_MODEL)
            tok = AutoTokenizer.from_pretrained(_MODEL)
            desc_name = getattr(getattr(model.config, "text_encoder", None), "_name_or_path", _MODEL)
            desc_tok = AutoTokenizer.from_pretrained(desc_name)
            _model, _tokenizer, _desc_tokenizer = model, tok, desc_tok
            _sr = int(getattr(model.config, "sampling_rate", 44_100))
            logger.info(f"Indic TTS ready (sample_rate={_sr}Hz).")
        except Exception as e:  # noqa: BLE001 — fail soft to Supertonic
            logger.warning(f"Indic TTS unavailable ({e}); ta/te/kn/ml will use Supertonic 'na'.")
            _model = None
        finally:
            _loaded = True
        return _model is not None


def synthesize_wav_indic(text: str, lang: str = "ta") -> bytes:
    """Synthesise Indic `text` to a WAV at the model's sample rate. Returns b"" when
    the engine is unavailable so the caller falls back to Supertonic."""
    if not text or not text.strip():
        return b""
    if not _load() or _model is None:
        return b""
    try:
        import torch

        desc_ids = _desc_tokenizer(_VOICE_DESC, return_tensors="pt").input_ids
        prompt_ids = _tokenizer(text, return_tensors="pt").input_ids
        with torch.no_grad():
            gen = _model.generate(input_ids=desc_ids, prompt_input_ids=prompt_ids)
        audio = gen.cpu().numpy().squeeze().astype(np.float32)
        return _encode_wav(audio, _sr)
    except Exception as e:  # noqa: BLE001
        logger.error(f"Indic TTS synthesis failed ({e}); falling back.")
        return b""


__all__ = ["synthesize_wav_indic", "INDIC_LANGS"]
