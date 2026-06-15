"""
Language detection and code-switching utilities for IRA's multilingual voice layer.

Supported language families:
  English          : en
  Indian languages : hi (Hindi), ta (Tamil), te (Telugu), kn (Kannada),
                     ml (Malayalam), mr (Marathi), gu (Gujarati), bn (Bengali), pa (Punjabi)
  European         : de (German), fr (French), it (Italian), es (Spanish)
  Asian            : zh (Chinese Mandarin), ja (Japanese)
  Middle Eastern   : ar (Arabic)

Auto-detection uses Faster-Whisper's built-in language ID (most accurate for speech)
and falls back to langdetect for text-level detection.
"""

from __future__ import annotations

# ── Language metadata ─────────────────────────────────────────────────────────

# Maps ISO 639-1 → human-readable name for logging
LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "hi": "Hindi",
    "ta": "Tamil",
    "te": "Telugu",
    "kn": "Kannada",
    "ml": "Malayalam",
    "mr": "Marathi",
    "gu": "Gujarati",
    "bn": "Bengali",
    "pa": "Punjabi",
    "de": "German",
    "fr": "French",
    "it": "Italian",
    "es": "Spanish",
    "zh": "Chinese",
    "ja": "Japanese",
    "ar": "Arabic",
}

# Languages where Kokoro af_bella (English) sounds acceptable even for non-English
# (romanised pronunciation, understood by bilingual speakers)
KOKORO_SUPPORTED: frozenset[str] = frozenset({
    "en", "en-us", "en-gb",
    "de", "fr", "it", "es",  # Kokoro handles European languages reasonably
})

# Indian languages — route to piper-tts or IndicTTS (plug in Phase 4)
INDIC_LANGUAGES: frozenset[str] = frozenset({
    "hi", "ta", "te", "kn", "ml", "mr", "gu", "bn", "pa",
})

# Kokoro voice to use per language
KOKORO_VOICE_MAP: dict[str, str] = {
    "en":   "af_bella",   # Warm, professional female — IRA's primary voice
    "en-gb": "af_bella",
    "de":   "af_bella",   # Kokoro handles German with af_bella acceptably
    "fr":   "af_bella",
    "it":   "af_bella",
    "es":   "af_bella",
    "default": "af_bella",
}

# IRA greeting in each supported language
IRA_GREETINGS: dict[str, str] = {
    "en": "Hello, I am IRA — your Intelligent Responsive Assistant. How can I help you today?",
    "hi": "Namaste, main IRA hoon — aapki Intelligent Responsive Assistant. Aaj main aapki kaise madad kar sakti hoon?",
    "ta": "Vanakkam, naan IRA — ungal Intelligent Responsive Assistant. Inru ungalukku eppadi udava mudiyum?",
    "te": "Namaskaram, nenu IRA — meeru Intelligent Responsive Assistant. Nenu meeru ela sahaayapadagalanu?",
    "kn": "Namaskara, nanu IRA — nimma Intelligent Responsive Assistant. Idhu nanu nimage hoege saayi maadabahudhu?",
    "ml": "Namaskaram, ñaan IRA — ningalude Intelligent Responsive Assistant. Innalle engane sahaayikkanam?",
    "de": "Hallo, ich bin IRA — Ihre intelligente, reaktionsfähige Assistentin. Wie kann ich Ihnen heute helfen?",
    "fr": "Bonjour, je suis IRA — votre Assistante Intelligente et Réactive. Comment puis-je vous aider aujourd'hui?",
    "it": "Buongiorno, sono IRA — la sua Assistente Intelligente e Reattiva. Come posso aiutarla oggi?",
    "zh": "您好，我是IRA——您的智能响应助手。今天我能为您做些什么？",
    "ja": "こんにちは、IRAです — あなたのインテリジェント・レスポンシブ・アシスタントです。本日はどのようにお手伝いできますか？",
    "ar": "مرحباً، أنا إيرا — مساعدتك الذكية المستجيبة. كيف يمكنني مساعدتك اليوم؟",
}


def get_greeting(lang: str) -> str:
    """Return IRA's greeting in the detected language."""
    return IRA_GREETINGS.get(lang, IRA_GREETINGS["en"])


def get_kokoro_voice(lang: str) -> str:
    """Return the Kokoro voice ID for the given language."""
    return KOKORO_VOICE_MAP.get(lang, KOKORO_VOICE_MAP["default"])


def is_indic(lang: str) -> bool:
    return lang in INDIC_LANGUAGES


def normalise_lang(lang: str | None) -> str:
    """Normalise language code to 2-char ISO 639-1."""
    if not lang:
        return "en"
    code = lang.lower().split("-")[0].split("_")[0]
    return code if code in LANGUAGE_NAMES else "en"


def detect_language_text(text: str) -> str:
    """Detect language of a text string (fallback when Whisper doesn't provide it)."""
    try:
        from langdetect import detect
        return normalise_lang(detect(text))
    except Exception:
        return "en"
