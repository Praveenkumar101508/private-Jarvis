"""
BGE-large-en-v1.5 embedding service.
Runs on CPU to preserve all 20GB VRAM for the LLM inference engines.
Model is loaded once at startup and reused for every embedding call.
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from sentence_transformers import SentenceTransformer

from config import get_settings

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="embed")

# Fix L13: @lru_cache(maxsize=1) is not thread-safe on Python < 3.12 when the
# decorated function is called concurrently by multiple threads before the first
# result is cached.  _embed_sync() runs in a ThreadPoolExecutor with max_workers=2,
# so two callers arriving simultaneously before the model is warmed can each enter
# _get_model() and load the 1.3 GB model twice — wasting memory and time.
# Double-checked locking with an explicit Lock guarantees exactly one load.
_model_lock = threading.Lock()
_model_instance: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model_instance
    if _model_instance is None:
        with _model_lock:
            if _model_instance is None:   # second check inside the lock
                cfg = get_settings()
                _model_instance = SentenceTransformer(
                    cfg.embedding_model, device=cfg.embedding_device
                )
    return _model_instance


def _embed_sync(texts: list[str]) -> list[list[float]]:
    model = _get_model()
    # normalize_embeddings=True → cosine similarity == dot product (faster search)
    vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return vecs.tolist()


async def embed(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts asynchronously (offloaded to thread pool)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _embed_sync, texts)


async def embed_one(text: str) -> list[float]:
    results = await embed([text])
    return results[0]


def preload_model() -> None:
    """Call at startup to warm the model before the first request."""
    _get_model()
