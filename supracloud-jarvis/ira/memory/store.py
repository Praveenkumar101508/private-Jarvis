"""
Memory store — persists conversations and retrieves relevant memories via pgvector.

Two operations drive Jarvis's memory:
  store_message()  — saves each exchange and its embedding asynchronously
  retrieve()       — finds the top-K most relevant past memories for a given query
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime

from utils.db import acquire
from memory.embeddings import embed_one

logger = logging.getLogger("ira.memory")

# Fix #44: module-level set keeps strong references to background embedding tasks
# so Python's garbage collector cannot collect them before they finish.
# The asyncio event loop only holds a *weak* reference to tasks; without a live
# strong reference the task can be silently dropped mid-execution.
_background_tasks: set[asyncio.Task] = set()


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
    user_id: str,   # Fix P31: required — every embedding must be scoped to a user
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
    # Fix #44: keep a strong reference in the module-level set so the task
    # cannot be GC'd before it finishes; discard on completion to prevent growth.
    _t = asyncio.create_task(_store_embedding(msg_id, content, "message", user_id=user_id))
    _background_tasks.add(_t)
    _t.add_done_callback(_background_tasks.discard)
    _t.add_done_callback(lambda t: t.exception() and logger.warning(f"Embedding task failed: {t.exception()}"))
    return msg_id


async def _store_embedding(
    source_id: str,
    content: str,
    source_type: str,
    *,
    user_id: str = "system",   # Fix #34: tag every embedding with the owning user
) -> None:
    """Embed content and store the vector — runs as a background task."""
    try:
        vector = await embed_one(content)
        vector_str = "[" + ",".join(map(str, vector)) + "]"
        async with acquire() as conn:
            await conn.execute(
                """INSERT INTO memory_embeddings
                   (source_id, source_type, content, embedding, user_id)
                   VALUES ($1, $2, $3, $4::vector, $5)""",
                uuid.UUID(source_id), source_type, content, vector_str, user_id,
            )
    except Exception as e:
        logger.debug(f"Embedding store failed (non-fatal): {e}")


# ── Memory retrieval (RAG) ────────────────────────────────────────────────────

async def retrieve(
    query: str,
    user_id: str = "system",  # Fix #34: filter to the calling user's memories only
    top_k: int | None = None,
) -> list[dict]:
    """
    Find the top-K most semantically relevant memories for a query.

    Fix #34: results are scoped to ``user_id`` so users cannot see each other's
    memories. Pass user_id="system" to search across all owner-level memories.

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
               WHERE user_id = $3
               ORDER BY embedding <=> $1::vector
               LIMIT $2""",
            vector_str, k, user_id,
        )
    return [
        {"content": r["content"], "source_type": r["source_type"], "similarity": float(r["similarity"])}
        for r in rows
        if float(r["similarity"]) > 0.6   # Filter out weak matches
    ]


# ── Memory retention (Fix #75) ────────────────────────────────────────────────

async def purge_old_memories(retention_days: int = 90) -> int:
    """
    Delete memory embeddings older than ``retention_days``.

    Fix #75: without this the memory_embeddings table grows unbounded. Run
    weekly via the scheduler. Returns the number of rows deleted.

    Note: messages and conversations are NOT deleted — only the embedding
    vectors are purged. Chat history remains intact.
    """
    try:
        async with acquire() as conn:
            result = await conn.execute(
                # Fix #94: make_interval() avoids asyncpg type-inference ambiguity
                # with parameterised interval arithmetic ($1 * INTERVAL '1 day').
                "DELETE FROM memory_embeddings WHERE created_at < NOW() - make_interval(days => $1)",
                retention_days,
            )
        # asyncpg returns "DELETE N" as the status string
        count = int(result.split()[-1]) if result and result.startswith("DELETE") else 0
        logger.info(f"Memory retention: purged {count} embeddings older than {retention_days} days")
        return count
    except Exception as e:
        logger.error(f"Memory retention purge failed: {e}")
        return 0


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
