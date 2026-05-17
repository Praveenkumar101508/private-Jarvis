"""
Memory store — Redis for short-term, ChromaDB for long-term semantic memory.

Two-tier architecture:
  Short-term  (Redis)    — last N conversation turns, 7-day TTL
  Long-term   (ChromaDB) — semantically indexed exchange summaries, permanent
"""
import asyncio
import json
import uuid
from datetime import datetime, timezone

import redis.asyncio as aioredis
import structlog

from config import settings

log = structlog.get_logger()

MAX_SHORT_TERM_TURNS = 20
CHROMA_COLLECTION = "ira_memory"

# Minimum combined length before we bother embedding a turn into long-term memory
_MIN_EMBED_LEN = 40


class MemoryStore:
    def __init__(self):
        self._redis: aioredis.Redis | None = None
        self._chroma = None        # chromadb.AsyncHttpClient
        self._collection = None    # chroma collection handle

    # ── Redis helpers ─────────────────────────────────────────────────────────

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(
                settings.redis_url,
                password=settings.redis_password or None,
                decode_responses=True,
            )
        return self._redis

    # ── ChromaDB helpers ──────────────────────────────────────────────────────

    async def _get_collection(self):
        if self._collection is None:
            import chromadb
            self._chroma = await chromadb.AsyncHttpClient(
                host=settings.chroma_host,
                port=settings.chroma_port,
            )
            self._collection = await self._chroma.get_or_create_collection(
                name=CHROMA_COLLECTION,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    def _embed(self, text: str) -> list[float]:
        """Local sentence embedding — no cloud API required."""
        from sentence_transformers import SentenceTransformer
        if not hasattr(self, "_encoder"):
            self._encoder = SentenceTransformer("all-MiniLM-L6-v2")
        return self._encoder.encode(text, normalize_embeddings=True).tolist()

    # ── Short-term memory (Redis) ─────────────────────────────────────────────

    async def save_turn(self, session_id: str, user_msg: str, assistant_msg: str):
        r = await self._get_redis()
        key = f"ira:session:{session_id}:history"
        turn = json.dumps({
            "user": user_msg,
            "assistant": assistant_msg,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        await r.rpush(key, turn)
        await r.ltrim(key, -MAX_SHORT_TERM_TURNS, -1)
        await r.expire(key, 86400 * 7)  # 7-day TTL

        # Persist meaningful exchanges to long-term memory asynchronously
        combined = f"{user_msg} {assistant_msg}"
        if len(combined) >= _MIN_EMBED_LEN:
            asyncio.create_task(
                self._persist_long_term(session_id, user_msg, assistant_msg)
            )

    async def get_context(self, session_id: str, last_n: int = 10) -> str:
        try:
            r = await self._get_redis()
            key = f"ira:session:{session_id}:history"
            raw = await r.lrange(key, -last_n, -1)
            if not raw:
                return ""
            turns = [json.loads(t) for t in raw]
            lines = []
            for t in turns:
                lines.append(f"User: {t['user']}")
                lines.append(f"IRA: {t['assistant']}")
            return "\n".join(lines)
        except Exception as exc:
            log.warning("memory_load_failed", error=str(exc))
            return ""

    async def clear_session(self, session_id: str):
        r = await self._get_redis()
        await r.delete(f"ira:session:{session_id}:history")

    # ── Long-term semantic memory (ChromaDB) ──────────────────────────────────

    async def _persist_long_term(self, session_id: str, user_msg: str, assistant_msg: str):
        """Embed and store a conversation turn into the ChromaDB vector index."""
        try:
            collection = await self._get_collection()
            text = f"User: {user_msg}\nIRA: {assistant_msg}"
            embedding = await asyncio.get_event_loop().run_in_executor(
                None, self._embed, text
            )
            await collection.add(
                ids=[str(uuid.uuid4())],
                embeddings=[embedding],
                documents=[text],
                metadatas=[{
                    "session_id": session_id,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }],
            )
        except Exception as exc:
            log.warning("long_term_persist_failed", error=str(exc))

    async def semantic_recall(self, query: str, n_results: int = 5) -> str:
        """
        Search long-term memory for exchanges semantically similar to query.
        Returns a formatted string ready to inject into the LLM context.
        Silently degrades to empty string if ChromaDB is unreachable.
        """
        try:
            collection = await self._get_collection()
            embedding = await asyncio.get_event_loop().run_in_executor(
                None, self._embed, query
            )
            results = await collection.query(
                query_embeddings=[embedding],
                n_results=n_results,
                include=["documents", "metadatas", "distances"],
            )
            docs = results.get("documents", [[]])[0]
            distances = results.get("distances", [[]])[0]
            if not docs:
                return ""
            # Only include results with cosine similarity > 0.25 (distance < 0.75)
            relevant = [d for d, dist in zip(docs, distances) if dist < 0.75]
            if not relevant:
                return ""
            return "Relevant past context:\n" + "\n---\n".join(relevant)
        except Exception as exc:
            log.warning("semantic_recall_failed", error=str(exc))
            return ""

    # ── User preferences ──────────────────────────────────────────────────────

    async def save_user_preference(self, user_id: str, key: str, value: str):
        r = await self._get_redis()
        await r.hset(f"ira:user:{user_id}:prefs", key, value)

    async def get_user_preferences(self, user_id: str) -> dict:
        try:
            r = await self._get_redis()
            return await r.hgetall(f"ira:user:{user_id}:prefs")
        except Exception:
            return {}
