"""
IRA Offline Biometric Voice Verifier.

Uses SpeechBrain's ECAPA-TDNN model (spkrec-ecapa-voxceleb) — a state-of-the-art
speaker embedding model trained on VoxCeleb. Runs entirely on CPU inside the
ira-voice container. No cloud calls, no external APIs.

Architecture:
  1. Audio chunk (bytes, 16kHz PCM) → resample → extract ECAPA-TDNN embedding
  2. Cosine similarity vs. stored owner voice profile (pulled from DB once, cached)
  3. Return True if similarity ≥ BIOMETRIC_THRESHOLD (default 0.75)

Owner enrolment flow:
  POST /api/v1/voice/enroll  → admin submits ≥3 reference audio segments
  → Embeddings averaged → stored in voice_profiles table

Verification flow (per-utterance in voice/agent.py):
  is_owner_authenticated(audio_bytes) → bool
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import struct
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import Optional

import numpy as np

from config import get_settings

logger = logging.getLogger("ira.biometrics")

# Thread pool for CPU-bound embedding computation — keeps async loop responsive
_bio_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="biometrics")

# In-process cache for owner embedding (avoids DB round-trip per utterance)
_owner_embedding_cache: Optional[list[float]] = None


# ── Model loading ─────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _get_encoder():
    """
    Load ECAPA-TDNN speaker encoder (lazy, cached).
    Downloads ~100MB on first use to the HuggingFace cache volume.
    """
    try:
        from speechbrain.inference.speaker import EncoderClassifier
        encoder = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            run_opts={"device": "cpu"},
            savedir="/home/ira/.cache/speechbrain/spkrec-ecapa",
        )
        logger.info("ECAPA-TDNN speaker encoder loaded")
        return encoder
    except Exception as e:
        logger.error(f"Failed to load ECAPA-TDNN model: {e}")
        return None


# ── Audio preprocessing ───────────────────────────────────────────────────────

def _pcm_bytes_to_tensor(audio_bytes: bytes, sample_rate: int = 16000):
    """
    Convert raw PCM bytes (16-bit signed, mono) to a torch float tensor
    normalised to [-1, 1] range.
    """
    import torch
    n_samples = len(audio_bytes) // 2
    samples = struct.unpack(f"<{n_samples}h", audio_bytes)
    waveform = np.array(samples, dtype=np.float32) / 32768.0
    return torch.tensor(waveform).unsqueeze(0)  # shape: [1, samples]


def _compute_embedding_sync(audio_bytes: bytes) -> Optional[list[float]]:
    """
    Compute ECAPA-TDNN speaker embedding from raw 16kHz PCM bytes.
    Returns a 192-dimensional unit-normalised vector, or None on failure.
    Runs synchronously — call via run_in_executor.
    """
    try:
        import torch
        encoder = _get_encoder()
        if encoder is None:
            return None

        waveform = _pcm_bytes_to_tensor(audio_bytes)
        with torch.no_grad():
            embedding = encoder.encode_batch(waveform)
            # embedding shape: [1, 1, 192] → flatten to [192]
            vec = embedding.squeeze().cpu().numpy()
            # L2-normalise for cosine similarity via dot product
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
        return vec.tolist()
    except Exception as e:
        logger.warning(f"Embedding computation failed: {e}")
        return None


async def compute_embedding(audio_bytes: bytes) -> Optional[list[float]]:
    """Async wrapper — offloads CPU embedding work to thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_bio_executor, _compute_embedding_sync, audio_bytes)


# ── Cosine similarity ─────────────────────────────────────────────────────────

def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two L2-normalised vectors (= dot product)."""
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    return float(np.dot(va, vb))


# ── Owner profile management ──────────────────────────────────────────────────

async def _load_owner_profile() -> Optional[list[float]]:
    """
    Fetch the owner's stored voice embedding from the database.
    Result is cached in-process for the lifetime of the container.
    """
    global _owner_embedding_cache
    if _owner_embedding_cache is not None:
        return _owner_embedding_cache

    try:
        from utils.db import acquire
        async with acquire() as conn:
            row = await conn.fetchrow(
                "SELECT embedding FROM voice_profiles ORDER BY created_at DESC LIMIT 1"
            )
        if row and row["embedding"]:
            _owner_embedding_cache = json.loads(row["embedding"])
            logger.info("Owner voice profile loaded from database")
            return _owner_embedding_cache
    except Exception as e:
        logger.warning(f"Could not load owner voice profile: {e}")
    return None


async def save_owner_profile(embeddings: list[list[float]]) -> bool:
    """
    Average a list of reference embeddings and persist to the database.
    Call this during the voice enrolment flow (POST /voice/enroll).
    Returns True on success.
    """
    global _owner_embedding_cache

    if not embeddings:
        return False

    # Average and re-normalise
    matrix = np.array(embeddings, dtype=np.float32)
    avg = matrix.mean(axis=0)
    norm = np.linalg.norm(avg)
    if norm > 0:
        avg = avg / norm

    embedding_json = json.dumps(avg.tolist())

    try:
        from utils.db import acquire
        from config import get_settings
        cfg = get_settings()
        async with acquire() as conn:
            await conn.execute(
                """INSERT INTO voice_profiles (owner_name, embedding)
                   VALUES ($1, $2)
                   ON CONFLICT (owner_name) DO UPDATE
                   SET embedding=$2, updated_at=NOW()""",
                cfg.owner_name, embedding_json,
            )
        _owner_embedding_cache = avg.tolist()
        logger.info(f"Owner voice profile saved ({len(embeddings)} reference segments)")
        return True
    except Exception as e:
        logger.error(f"Failed to save owner voice profile: {e}")
        return False


def invalidate_profile_cache() -> None:
    """Force reload of owner profile on next verification call."""
    global _owner_embedding_cache
    _owner_embedding_cache = None


# ── Main verification entry point ─────────────────────────────────────────────

async def is_owner_authenticated(audio_bytes: bytes, session_id: str = "unknown") -> bool:
    """
    Verify whether the speaker in the audio chunk is the system owner.

    Args:
        audio_bytes: Raw PCM audio data (16-bit signed, mono, 16kHz).
        session_id:  Voice session identifier — written to biometric_audit table.

    Returns:
        True  → speaker matches owner profile with similarity ≥ threshold.
        False → no profile, model unavailable, or speaker does not match.

    Biometric verification is best-effort: if the model is unavailable
    (first-run download pending, out of memory), this returns False
    so the voice session degrades gracefully to public-access mode
    rather than crashing.
    """
    cfg = get_settings()

    # Require at least 1 second of audio for a reliable ECAPA-TDNN embedding. (#35)
    # 16kHz × 16-bit mono = 32 000 bytes/second.
    # 100ms (3 200 bytes) is far too short — embeddings from very short clips have
    # high variance and produce excessive false-positives / false-negatives.
    if not audio_bytes or len(audio_bytes) < 32_000:  # <1s at 16kHz 16-bit mono
        logger.debug(
            f"Audio too short for biometric check: {len(audio_bytes)} bytes "
            f"(need ≥32 000 / 1 s)"
        )
        return False

    # Load the owner's reference profile
    owner_profile = await _load_owner_profile()
    if owner_profile is None:
        logger.debug("No owner voice profile enrolled — biometric auth unavailable")
        return False

    # Compute embedding for incoming audio
    embedding = await compute_embedding(audio_bytes)
    if embedding is None:
        return False

    # Cosine similarity check
    similarity = cosine_similarity(embedding, owner_profile)
    authenticated = similarity >= cfg.biometric_threshold

    logger.info(
        f"Biometric check: similarity={similarity:.3f} "
        f"threshold={cfg.biometric_threshold} "
        f"result={'PASS' if authenticated else 'FAIL'}"
    )

    # Persist every check to biometric_audit for security auditing
    try:
        from utils.db import acquire
        async with acquire() as conn:
            await conn.execute(
                """INSERT INTO biometric_audit
                   (session_id, similarity, threshold, result, source)
                   VALUES ($1, $2, $3, $4, 'voice')""",
                session_id, float(similarity), float(cfg.biometric_threshold), authenticated,
            )
    except Exception as audit_err:
        logger.debug(f"Biometric audit write failed (non-fatal): {audit_err}")

    return authenticated
