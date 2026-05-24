"""
Memory store — persists conversations and retrieves relevant memories via pgvector.

Two operations drive Jarvis's memory:
  store_message()  — saves each exchange and its embedding asynchronously
  retrieve()       — finds the top-K most relevant past memories for a given query
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

from utils.db import acquire
from memory.embeddings import embed_one


# ── Conversation persistence ───────────────────────────────────────────────────

async def ensure_conversation(session_id: str) -> str:
    """Return the conversation UUID for a session, creating one if needed."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM conversations WHERE session_id = $1 ORDER BY created_at DESC LIMIT 1",
            session_id,
        )
        if row:
            return str(row["id"])
        conv_id = str(uuid.uuid4())
        await conn.execute(
            "INSERT INTO conversations (id, session_id) VALUES ($1, $2)",
            uuid.UUID(conv_id), session_id,
        )
        return conv_id


async def save_message(
    conversation_id: str,
    role: str,
    content: str,
    *,
    model_used: str | None = None,
    latency_ms: int | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
) -> str:
    """Persist a message and kick off async embedding storage."""
    msg_id = str(uuid.uuid4())
    async with acquire() as conn:
        await conn.execute(
            """INSERT INTO messages
               (id, conversation_id, role, content, model_used, latency_ms, tokens_in, tokens_out)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
            uuid.UUID(msg_id),
            uuid.UUID(conversation_id),
            role, content, model_used, latency_ms, tokens_in, tokens_out,
        )
    # Embed and store asynchronously — keep reference so task isn't GC'd mid-flight
    _t = asyncio.create_task(_store_embedding(msg_id, content, "message"))
    _t.add_done_callback(lambda t: t.exception() and logger.warning(f"Embedding task failed: {t.exception()}"))
    return msg_id


async def _store_embedding(source_id: str, content: str, source_type: str) -> None:
    """Embed content and store the vector — runs as a background task."""
    try:
        vector = await embed_one(content)
        vector_str = "[" + ",".join(map(str, vector)) + "]"
        async with acquire() as conn:
            await conn.execute(
                """INSERT INTO memory_embeddings (source_id, source_type, content, embedding)
                   VALUES ($1, $2, $3, $4::vector)""",
                uuid.UUID(source_id), source_type, content, vector_str,
            )
    except Exception:
        pass  # Embedding failure must never crash the main response path


# ── Memory retrieval (RAG) ────────────────────────────────────────────────────

async def retrieve(query: str, top_k: int | None = None) -> list[dict]:
    """
    Find the top-K most semantically relevant memories for a query.
    Returns a list of {"content": str, "source_type": str, "similarity": float}.
    """
    from config import get_settings
    cfg = get_settings()
    k = top_k or cfg.rag_top_k

    query_vec = await embed_one(query)
    vector_str = "[" + ",".join(map(str, query_vec)) + "]"

    async with acquire() as conn:
        rows = await conn.fetch(
            """SELECT content, source_type,
                      1 - (embedding <=> $1::vector) AS similarity
               FROM memory_embeddings
               ORDER BY embedding <=> $1::vector
               LIMIT $2""",
            vector_str, k,
        )
    return [
        {"content": r["content"], "source_type": r["source_type"], "similarity": float(r["similarity"])}
        for r in rows
        if float(r["similarity"]) > 0.6   # Filter out weak matches
    ]


async def get_recent_messages(conversation_id: str, limit: int = 20) -> list[dict]:
    """Retrieve the most recent messages for context injection."""
    async with acquire() as conn:
        rows = await conn.fetch(
            """SELECT role, content FROM messages
               WHERE conversation_id = $1
               ORDER BY created_at DESC LIMIT $2""",
            uuid.UUID(conversation_id), limit,
        )
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
