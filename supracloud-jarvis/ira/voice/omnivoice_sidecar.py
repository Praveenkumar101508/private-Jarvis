"""voice/omnivoice_sidecar.py — OmniVoice TTS worker, run in its OWN venv.

OmniVoice requires transformers>=5.3 and CUDA torch (~2.8), which conflict head-on
with IRA's pins (sentence-transformers caps transformers <5; IRA ships CPU torch
2.4.1). So OmniVoice runs OUT-OF-PROCESS in a dedicated venv and IRA drives it over
stdio. This script is that worker; voice/tts_omnivoice.py is the IRA-side client.

Launch (from the ira package dir, with the sidecar venv's python):
    python -m voice.omnivoice_sidecar --model k2-fsa/OmniVoice --device cuda:0 --dtype float16

Set up the sidecar venv once (see voice/omnivoice_sidecar.requirements.txt):
    python3.10 -m venv .venv-omnivoice
    .venv-omnivoice/bin/pip install torch==2.8.0+cu128 torchaudio==2.8.0+cu128 \
        --extra-index-url https://download.pytorch.org/whl/cu128
    .venv-omnivoice/bin/pip install -r voice/omnivoice_sidecar.requirements.txt

PROTOCOL (voice/omnivoice_protocol.py): stdin carries request frames, stdout carries
response frames. stdout is reserved for frames ONLY — all logging goes to stderr so it
never corrupts the binary channel.

  Request  {"op":"ping"}                              → {"ok":true,"pong":true}
  Request  {"op":"synth","text":...,"ref_audio":...,  → {"ok":true,"sr":24000,
            "ref_text":...,"instruct":...,                "samples":N,"format":"f32le"}
            "language":...,"num_step":16,"speed":1.0}     + raw payload (f32le PCM @24k)
  On error                                            → {"ok":false,"error":"..."}

Apache-2.0 OmniVoice is wrapped directly; no code is copied from the AGPL Studio.
"""
from __future__ import annotations

import argparse
import logging
import sys

from voice.omnivoice_protocol import read_message, write_message

logger = logging.getLogger("ira.omnivoice.sidecar")

# Holds the lazily-loaded model so we load weights exactly once, on first synth.
_model = None
_cfg: dict = {}


def _load_model():
    """Load OmniVoice once (heavy: pulls torch + transformers + the model)."""
    global _model
    if _model is not None:
        return _model
    import torch  # noqa: F401 - imported for dtype resolution
    from omnivoice import OmniVoice

    dtype = getattr(torch, _cfg.get("dtype", "float16"), torch.float16)
    logger.info("Loading OmniVoice %s on %s (%s)...",
                _cfg["model"], _cfg["device"], _cfg.get("dtype", "float16"))
    _model = OmniVoice.from_pretrained(_cfg["model"], device_map=_cfg["device"], dtype=dtype)
    logger.info("OmniVoice ready.")
    return _model


def _synthesize(req: dict) -> bytes:
    """Run one synthesis request → 24 kHz mono float32 little-endian PCM bytes."""
    import numpy as np

    model = _load_model()
    kwargs: dict = {"text": req["text"]}
    for key in ("ref_audio", "ref_text", "instruct", "language", "num_step", "speed", "duration"):
        val = req.get(key)
        if val is not None:
            kwargs[key] = val
    audio = model.generate(**kwargs)          # list[np.ndarray] shape (T,) @ 24 kHz
    samples = audio[0] if isinstance(audio, (list, tuple)) else audio
    return np.asarray(samples, dtype="<f4").tobytes()


def _handle(req: dict):
    op = req.get("op")
    if op == "ping":
        return {"ok": True, "pong": True}, b""
    if op == "synth":
        pcm = _synthesize(req)
        return {"ok": True, "sr": 24000, "samples": len(pcm) // 4, "format": "f32le"}, pcm
    return {"ok": False, "error": f"unknown op: {op!r}"}, b""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OmniVoice TTS sidecar")
    parser.add_argument("--model", default="k2-fsa/OmniVoice")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--dtype", default="float16")
    args = parser.parse_args(argv)
    _cfg.update(model=args.model, device=args.device, dtype=args.dtype)

    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
    logger.info("OmniVoice sidecar started (model=%s device=%s).", args.model, args.device)

    while True:
        msg = read_message(stdin)
        if msg is None:
            break  # parent closed the pipe → exit
        req, _payload = msg
        try:
            header, payload = _handle(req)
        except Exception as exc:  # noqa: BLE001 - report, keep serving
            logger.exception("synthesis failed")
            header, payload = {"ok": False, "error": str(exc)[:500]}, b""
        write_message(stdout, header, payload)
    logger.info("OmniVoice sidecar exiting.")
    return 0


if __name__ == "__main__":  # pragma: no cover - runs only in the sidecar venv
    raise SystemExit(main())
