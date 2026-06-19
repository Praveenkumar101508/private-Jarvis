"""voice/tts_omnivoice.py — IRA-side client for the OmniVoice TTS sidecar.

OmniVoice (k2-fsa, Apache-2.0) is a 600+-language zero-shot voice-cloning TTS. Its
deps (transformers>=5.3, CUDA torch ~2.8) conflict with IRA's pins, so it runs in a
separate venv as a subprocess (voice/omnivoice_sidecar.py). This module is the
in-process client: it manages that subprocess, speaks the stdio protocol, and adapts
OmniVoice's 24 kHz output to IRA's two TTS surfaces:

  - HTTP POST /voice/say  → synthesize_wav_omnivoice() → 44.1 kHz WAV bytes
  - LiveKit realtime agent → IRAOmniVoiceTTS (48 kHz int16), mirroring IRASupertonicTTS

Selection is via the existing IRA_VOICE_ENGINE flag (= "omnivoice"); everything is
fail-soft — if the sidecar venv / model / GPU is absent, callers fall back to the
existing engines and IRA's behaviour is unchanged. Heavy deps (numpy/scipy) are
imported lazily so this module loads in the lightweight (no-numpy) test env.

Config via env:
  IRA_OMNIVOICE_PYTHON     path to the sidecar venv's python (REQUIRED to enable)
  IRA_OMNIVOICE_MODEL      HF model id            (default "k2-fsa/OmniVoice")
  IRA_OMNIVOICE_DEVICE     torch device           (default "cuda:0")
  IRA_OMNIVOICE_DTYPE      torch dtype            (default "float16")
  IRA_OMNIVOICE_STEPS      diffusion steps        (default 16; 32 = higher quality)
  IRA_OMNIVOICE_REF_AUDIO  owner reference clip for voice cloning (optional)
  IRA_OMNIVOICE_REF_TEXT   transcript of the ref clip (optional; auto-transcribed if omitted)
  IRA_OMNIVOICE_INSTRUCT   voice-design string, e.g. "female, warm, indian accent" (optional)
  IRA_OMNIVOICE_CWD        cwd for the sidecar (default: the ira package dir)
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
from math import gcd
from typing import Optional, Tuple

from voice.omnivoice_protocol import read_message, write_message

# LiveKit Agents is only needed for the realtime plugin classes below. Import it
# softly so this module (and tts_factory) loads on a host without livekit — the
# HTTP synth path and the unit tests need that. (Same pattern as voice/tts.py.)
try:
    from livekit.agents import tts, utils
    from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions
    _TTSBase = tts.TTS
    _ChunkedStreamBase = tts.ChunkedStream
    _LIVEKIT_AVAILABLE = True
except Exception:  # pragma: no cover - only on hosts without livekit-agents
    tts = utils = None
    DEFAULT_API_CONNECT_OPTIONS = APIConnectOptions = None
    _TTSBase = _ChunkedStreamBase = object
    _LIVEKIT_AVAILABLE = False

logger = logging.getLogger("ira.tts.omnivoice")

# Audio format constants
OMNIVOICE_SAMPLE_RATE = 24_000   # OmniVoice native output
LIVEKIT_SAMPLE_RATE = 48_000     # LiveKit realtime contract
SAY_SAMPLE_RATE = 44_100         # HTTP /voice/say contract (matches Supertonic)

_DEFAULT_MODEL = os.getenv("IRA_OMNIVOICE_MODEL", "k2-fsa/OmniVoice")
_DEFAULT_DEVICE = os.getenv("IRA_OMNIVOICE_DEVICE", "cuda:0")
_DEFAULT_DTYPE = os.getenv("IRA_OMNIVOICE_DTYPE", "float16")
_DEFAULT_STEPS = int(os.getenv("IRA_OMNIVOICE_STEPS", "16"))


def _default_cwd() -> str:
    """The ira package dir (parent of voice/), so `-m voice.omnivoice_sidecar` resolves."""
    return os.getenv("IRA_OMNIVOICE_CWD") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def is_available() -> Tuple[bool, str]:
    """Whether OmniVoice can be attempted. Returns (False, reason) when it cannot,
    so callers/CI degrade cleanly without a GPU, model, or sidecar venv."""
    py = os.getenv("IRA_OMNIVOICE_PYTHON", "").strip()
    if not py:
        return False, "IRA_OMNIVOICE_PYTHON not set (path to the OmniVoice sidecar venv python)"
    if not os.path.isfile(py):
        return False, f"OmniVoice sidecar python not found: {py}"
    return True, "ok"


def _omni_lang(lang: Optional[str]) -> str:
    """OmniVoice handles 600+ languages, so pass the ISO 639-1 code straight through."""
    return (lang or "en").lower().split("-")[0]


# ── Sidecar subprocess client ────────────────────────────────────────────────

class OmniVoiceSidecar:
    """Manages the OmniVoice worker subprocess and the request/response protocol.

    One request at a time (guarded by a lock); the worker is spawned lazily on first
    use and respawned if it has died. All failures return empty audio (fail-soft).
    """

    def __init__(self, python: str, *, model: str, device: str, dtype: str, cwd: str):
        self._python = python
        self._model = model
        self._device = device
        self._dtype = dtype
        self._cwd = cwd
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    def _spawn(self) -> None:
        cmd = [self._python, "-m", "voice.omnivoice_sidecar",
               "--model", self._model, "--device", self._device, "--dtype", self._dtype]
        logger.info("Starting OmniVoice sidecar: %s", " ".join(cmd))
        self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      cwd=self._cwd)

    def _ensure(self) -> subprocess.Popen:
        if self._proc is None or self._proc.poll() is not None:
            self._spawn()
        return self._proc  # type: ignore[return-value]

    def _kill(self) -> None:
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:  # noqa: BLE001
                pass
            self._proc = None

    def _request(self, header: dict) -> Optional[Tuple[dict, bytes]]:
        with self._lock:
            proc = self._ensure()
            try:
                write_message(proc.stdin, header)
                resp = read_message(proc.stdout)
            except (BrokenPipeError, OSError, ValueError) as exc:
                logger.warning("OmniVoice sidecar I/O error: %s", exc)
                self._kill()
                return None
            if resp is None:
                logger.warning("OmniVoice sidecar closed the connection unexpectedly")
                self._kill()
                return None
            return resp

    def synth(self, text: str, *, ref_audio: Optional[str] = None, ref_text: Optional[str] = None,
              instruct: Optional[str] = None, language: Optional[str] = None,
              num_step: Optional[int] = None, speed: Optional[float] = None) -> bytes:
        """Synthesize → 24 kHz mono float32 little-endian PCM bytes (b"" on failure)."""
        header: dict = {"op": "synth", "text": text}
        for key, val in (("ref_audio", ref_audio), ("ref_text", ref_text), ("instruct", instruct),
                         ("language", language), ("num_step", num_step), ("speed", speed)):
            if val is not None:
                header[key] = val
        resp = self._request(header)
        if resp is None:
            return b""
        hdr, pcm = resp
        if not hdr.get("ok"):
            logger.warning("OmniVoice synth error: %s", hdr.get("error"))
            return b""
        return pcm

    def ping(self) -> bool:
        resp = self._request({"op": "ping"})
        return bool(resp and resp[0].get("ok"))

    def close(self) -> None:
        with self._lock:
            if self._proc is None:
                return
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()
                self._proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                self._kill()
            else:
                self._proc = None


_sidecar: Optional[OmniVoiceSidecar] = None
_sidecar_lock = threading.Lock()


def _get_sidecar() -> Optional[OmniVoiceSidecar]:
    """Return the singleton sidecar client, or None if OmniVoice is unavailable."""
    global _sidecar
    if _sidecar is not None:
        return _sidecar
    ok, reason = is_available()
    if not ok:
        logger.info("OmniVoice unavailable: %s", reason)
        return None
    with _sidecar_lock:
        if _sidecar is None:
            _sidecar = OmniVoiceSidecar(
                os.getenv("IRA_OMNIVOICE_PYTHON", "").strip(),
                model=_DEFAULT_MODEL, device=_DEFAULT_DEVICE, dtype=_DEFAULT_DTYPE,
                cwd=_default_cwd(),
            )
    return _sidecar


# ── Audio adaptation (lazy numpy/scipy — kept out of import for the test env) ──

def _resample_f32(audio, src_sr: int, dst_sr: int):
    import numpy as np

    arr = np.asarray(audio, dtype=np.float32)
    if src_sr == dst_sr or arr.size == 0:
        return arr
    g = gcd(src_sr, dst_sr)
    up, down = dst_sr // g, src_sr // g
    try:
        from scipy.signal import resample_poly  # prod dep (via scikit-learn); not in test deps
        out = resample_poly(arr, up, down)
    except Exception:  # noqa: BLE001 - fall back to linear interpolation without scipy
        n = int(round(arr.size * dst_sr / src_sr))
        out = np.interp(np.linspace(0, arr.size, num=n, endpoint=False),
                        np.arange(arr.size), arr)
    return np.clip(out, -1.0, 1.0).astype(np.float32)


def _pcm_to_int16_bytes(pcm_f32le: bytes, src_sr: int, dst_sr: int) -> bytes:
    import numpy as np

    audio = np.frombuffer(pcm_f32le, dtype="<f4")
    if audio.size == 0:
        return b""
    audio = _resample_f32(audio, src_sr, dst_sr)
    return (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()


def _pcm_to_wav(pcm_f32le: bytes, src_sr: int, dst_sr: int) -> bytes:
    import io
    import wave

    pcm16 = _pcm_to_int16_bytes(pcm_f32le, src_sr, dst_sr)
    if not pcm16:
        return b""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(dst_sr)
        wf.writeframes(pcm16)
    return buf.getvalue()


# ── HTTP /voice/say path ──────────────────────────────────────────────────────

def synthesize_wav_omnivoice(text: str, lang: str = "en", voice: Optional[str] = None,
                             steps: Optional[int] = None) -> bytes:
    """Synthesize `text` to a 44.1 kHz mono 16-bit WAV via OmniVoice. Returns b"" on
    any failure so the caller (synthesize_say) can fall back to Supertonic/Indic.

    `voice` is accepted for signature parity with the Supertonic path; OmniVoice picks
    its voice from the configured reference clip (cloning) or instruct (design) instead.
    """
    client = _get_sidecar()
    if client is None:
        return b""
    pcm = client.synth(
        text,
        ref_audio=os.getenv("IRA_OMNIVOICE_REF_AUDIO") or None,
        ref_text=os.getenv("IRA_OMNIVOICE_REF_TEXT") or None,
        instruct=os.getenv("IRA_OMNIVOICE_INSTRUCT") or None,
        language=_omni_lang(lang),
        num_step=int(steps) if steps else _DEFAULT_STEPS,
    )
    if not pcm:
        return b""
    try:
        return _pcm_to_wav(pcm, OMNIVOICE_SAMPLE_RATE, SAY_SAMPLE_RATE)
    except Exception as exc:  # noqa: BLE001
        logger.warning("OmniVoice WAV encode failed: %s", exc)
        return b""


# ── LiveKit realtime plugin (mirrors IRASupertonicTTS; validated on the voice host) ──

class IRAOmniVoiceTTS(_TTSBase):
    """LiveKit Agents 1.x TTS plugin backed by the OmniVoice sidecar.

    Drop-in for IRASupertonicTTS: same (voice, speed) constructor, streaming=False,
    48 kHz int16 output contract.
    """

    def __init__(self, voice: Optional[str] = None, speed: float = 1.0):
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=LIVEKIT_SAMPLE_RATE,
            num_channels=1,
        )
        self._voice = voice
        self._speed = speed

    def synthesize(self, text: str, *, conn_options=DEFAULT_API_CONNECT_OPTIONS) -> "IRAOmniVoiceChunkedStream":
        return IRAOmniVoiceChunkedStream(tts=self, input_text=text, conn_options=conn_options)


class IRAOmniVoiceChunkedStream(_ChunkedStreamBase):
    """Synthesizes the full utterance via the sidecar, resamples 24→48 kHz, emits."""

    def __init__(self, *, tts: "IRAOmniVoiceTTS", input_text: str, conn_options):
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._speed = tts._speed

    async def _run(self, output_emitter) -> None:  # pragma: no cover - validated on the voice host
        import asyncio

        loop = asyncio.get_running_loop()
        client = _get_sidecar()
        output_emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=LIVEKIT_SAMPLE_RATE,
            num_channels=1,
            mime_type="audio/pcm",
        )
        if client is None:
            output_emitter.flush()
            return
        lang = _omni_lang(os.getenv("IRA_TTS_LANG", "en"))
        pcm = await loop.run_in_executor(None, lambda: client.synth(
            self.input_text,
            ref_audio=os.getenv("IRA_OMNIVOICE_REF_AUDIO") or None,
            instruct=os.getenv("IRA_OMNIVOICE_INSTRUCT") or None,
            language=lang, num_step=_DEFAULT_STEPS, speed=self._speed,
        ))
        if pcm:
            output_emitter.push(_pcm_to_int16_bytes(pcm, OMNIVOICE_SAMPLE_RATE, LIVEKIT_SAMPLE_RATE))
        output_emitter.flush()


__all__ = [
    "is_available", "synthesize_wav_omnivoice", "OmniVoiceSidecar",
    "IRAOmniVoiceTTS", "OMNIVOICE_SAMPLE_RATE", "SAY_SAMPLE_RATE", "LIVEKIT_SAMPLE_RATE",
]
