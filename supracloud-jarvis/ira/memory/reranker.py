"""
A2: BGE reranker (cross-encoder) service.

Reorders already-retrieved memory candidates by query<->document relevance, a
big precision win over raw vector distance. Runs on CPU to preserve all 20GB
VRAM for the LLM. Loaded once at first use and reused for every call.

IMPORTANT: this is a SEPARATE model from the embedder. It scores (query, doc)
pairs on the fly and NEVER changes the stored 1024-dim embeddings or the DB —
so it is dimension-safe by construction.
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

from sentence_transformers import CrossEncoder

from config import get_settings

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rerank")

# Same double-checked-locking pattern as memory/embeddings.py (Fix L13): the
# ThreadPoolExecutor can enter _get_model() from two threads before the first
# load completes; the lock guarantees the cross-encoder is loaded exactly once.
_model_lock = threading.Lock()
_model_instance: CrossEncoder | None = None


def _get_model() -> CrossEncoder:
    global _model_instance
    if _model_instance is None:
        with _model_lock:
            if _model_instance is None:   # second check inside the lock
                cfg = get_settings()
                _model_instance = CrossEncoder(
                    cfg.reranker_model, device=cfg.reranker_device
                )
    return _model_instance


def _rerank_sync(query: str, docs: list[str]) -> list[float]:
    model = _get_model()
    pairs = [[query, d] for d in docs]
    scores = model.predict(pairs, show_progress_bar=False)
    return [float(s) for s in scores]


async def rerank(query: str, docs: list[str]) -> list[float]:
    """Return one relevance score per doc (higher = more relevant).

    Offloaded to the thread pool so the event loop is never blocked.
    """
    if not docs:
        return []
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _rerank_sync, query, docs)


def preload_model() -> None:
    """Call at startup to warm the cross-encoder before the first request."""
    _get_model()
