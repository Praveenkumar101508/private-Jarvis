"""
BGE-large-en-v1.5 embedding service.
Runs on CPU to preserve all 20GB VRAM for the LLM inference engines.
Model is loaded once at startup and reused for every embedding call.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import numpy as np
from sentence_transformers import SentenceTransformer

from config import get_settings

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="embed")


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    cfg = get_settings()
    return SentenceTransformer(cfg.embedding_model, device=cfg.embedding_device)


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
