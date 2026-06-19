"""voice/omnivoice_protocol.py — length-prefixed stdio framing for the OmniVoice sidecar.

OmniVoice (transformers>=5.3, CUDA torch) cannot share IRA's process — it lives in
its own venv and is driven as a subprocess. This module is the ONE definition of the
wire protocol, shared by the IRA-side client (voice/tts_omnivoice.py) and the sidecar
(voice/omnivoice_sidecar.py).

Dependency-free on purpose: only stdlib, so it imports cleanly in BOTH the IRA venv
and the (separate) OmniVoice venv, and is unit-testable without numpy/torch/omnivoice.

Frame = 4-byte big-endian length, then a body of that many bytes. The body is a JSON
header line, a newline, then an optional raw binary payload (e.g. PCM samples, which
may contain newline bytes — hence length-prefixing, not line-delimiting).
"""
from __future__ import annotations

import json
import struct
from typing import BinaryIO, Optional, Tuple

# Safety cap so a corrupt length prefix can't trigger a huge allocation.
MAX_FRAME_BYTES = 256 * 1024 * 1024  # 256 MB


def _read_exact(stream: BinaryIO, n: int) -> Optional[bytes]:
    """Read exactly n bytes, or return None on clean/partial EOF."""
    buf = bytearray()
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            return None  # EOF before the full frame
        buf += chunk
    return bytes(buf)


def write_message(stream: BinaryIO, header: dict, payload: bytes = b"") -> None:
    """Write one framed message (header dict + optional binary payload) and flush."""
    body = json.dumps(header, separators=(",", ":")).encode("utf-8") + b"\n" + payload
    stream.write(struct.pack(">I", len(body)))
    stream.write(body)
    stream.flush()


def read_message(stream: BinaryIO) -> Optional[Tuple[dict, bytes]]:
    """Read one framed message → (header, payload), or None on EOF/closed stream.

    Raises ValueError on a length prefix beyond MAX_FRAME_BYTES (corrupt/hostile).
    """
    prefix = _read_exact(stream, 4)
    if prefix is None:
        return None
    (length,) = struct.unpack(">I", prefix)
    if length > MAX_FRAME_BYTES:
        raise ValueError(f"frame too large: {length} bytes")
    body = _read_exact(stream, length)
    if body is None:
        return None
    nl = body.find(b"\n")
    if nl < 0:
        return json.loads(body.decode("utf-8")), b""
    header = json.loads(body[:nl].decode("utf-8"))
    return header, body[nl + 1:]


__all__ = ["write_message", "read_message", "MAX_FRAME_BYTES"]
