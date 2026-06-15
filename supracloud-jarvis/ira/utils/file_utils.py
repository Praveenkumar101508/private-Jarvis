"""
File utilities — safe upload helpers.

read_with_size_cap() reads a FastAPI UploadFile in chunks, enforcing a hard
limit before any bytes land in RAM.  This prevents OOM denial-of-service from
maliciously large uploads.
"""

from __future__ import annotations

from fastapi import HTTPException, UploadFile

_CHUNK = 64 * 1024  # 64 KiB read chunks


async def read_with_size_cap(file: UploadFile, max_bytes: int = 50 * 1024 * 1024) -> bytes:
    """
    Read *file* in chunks, raising HTTP 413 the moment accumulated bytes
    exceed *max_bytes* (default 50 MiB).

    Why chunked instead of read-then-check:
      A naive ``await file.read()`` buffers the entire upload before the
      size check runs, allowing an attacker to exhaust server RAM.  Reading
      in chunks caps memory usage at roughly *max_bytes + _CHUNK*.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            max_mb = max_bytes // (1024 * 1024)
            raise HTTPException(
                status_code=413,
                detail=f"Upload too large. Maximum allowed size is {max_mb} MB.",
            )
        chunks.append(chunk)
    return b"".join(chunks)
