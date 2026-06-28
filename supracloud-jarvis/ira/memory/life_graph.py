"""
memory/life_graph.py — IRA's Life Context Graph (Feature 1).

A structured entity + edge layer that lives *beside* the pgvector memory store in the
same Postgres database. The vector store (``memory_embeddings``) gives fuzzy semantic
recall; this graph gives structured traversal — "everything connected to the Luxembourg
application" — by walking typed edges between entities.

Design constraints (kept deliberately):
  * Same DB, same connection handling (``utils.db.acquire``), same parameterized-SQL
    style as ``memory/store.py``. No new database, no ORM.
  * Entity descriptions are embedded with the EXACT existing BGE function
    (``memory.embeddings.embed_one``) — embeddings are never re-implemented here.
  * Gated by the IRA_LIFE_GRAPH flag, read via the SAME mechanism as IRA_USE_CORTEX.
    When the flag is OFF, no public function touches the database — they return the
    empty/None shape their signature promises.
  * Fail-closed: any DB or embedding error is logged and yields empty/None, never a
    partial graph and never a raised exception to the caller.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Optional

from utils.db import acquire

logger = logging.getLogger("ira.memory.life_graph")

# Truthy set mirrors IRA_USE_CORTEX exactly (config.py). New OFF-by-default flag.
_TRUTHY = ("1", "true", "yes", "on")


async def embed_one(text: str) -> list[float]:
    """Embed via the EXACT existing BGE function. Lazy-imported so this module loads
    in the lightweight (no-numpy) test env, mirroring voice/voice_output.py."""
    from memory.embeddings import embed_one as _embed_one
    return await _embed_one(text)


def graph_enabled() -> bool:
    """True only when IRA_LIFE_GRAPH is explicitly enabled. Defaults OFF."""
    return os.getenv("IRA_LIFE_GRAPH", "false").strip().lower() in _TRUTHY


def _vector_literal(vec: list[float]) -> str:
    """Render a float list as a pgvector literal, matching memory/store.py."""
    return "[" + ",".join(map(str, vec)) + "]"


# ── Entity writes ─────────────────────────────────────────────────────────────

async def upsert_entity(
    type: str,
    name: str,
    description: str | None = None,
    *,
    embed_description: bool = True,
) -> Optional[str]:
    """Create or update an entity, keyed on (type, name). Returns its id, or None.

    On conflict the description / embedding / updated_at are refreshed. The BGE
    embedding is computed only when a description is present; embedding failure is
    non-fatal (the row is still written without a vector).
    """
    if not graph_enabled():
        return None
    if not type or not name:
        logger.debug("life_graph.upsert_entity: type and name are required")
        return None

    vector_str: Optional[str] = None
    if embed_description and description:
        try:
            vector_str = _vector_literal(await embed_one(description))
        except Exception as e:  # embedding is best-effort; entity still upserts
            logger.debug(f"life_graph: description embed failed (non-fatal): {e}")

    try:
        async with acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO entities (type, name, description, embedding)
                   VALUES ($1, $2, $3, $4::vector)
                   ON CONFLICT (type, name) DO UPDATE
                     SET description = EXCLUDED.description,
                         embedding   = EXCLUDED.embedding,
                         updated_at  = NOW()
                   RETURNING id""",
                type, name, description, vector_str,
            )
        return str(row["id"]) if row else None
    except Exception as e:
        logger.warning(f"life_graph.upsert_entity failed (fail-closed): {e}")
        return None


async def add_edge(
    src_entity_id: str,
    dst_entity_id: str,
    relation: str,
    *,
    weight: float = 1.0,
) -> Optional[str]:
    """Create or update a directed (src -> dst) edge of type ``relation``.

    Keyed on (src, dst, relation): re-asserting an edge updates its weight rather
    than duplicating it. Returns the edge id, or None on any error.
    """
    if not graph_enabled():
        return None
    if not src_entity_id or not dst_entity_id or not relation:
        logger.debug("life_graph.add_edge: src, dst and relation are required")
        return None
    try:
        async with acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO edges (src_entity_id, dst_entity_id, relation, weight)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (src_entity_id, dst_entity_id, relation) DO UPDATE
                     SET weight = EXCLUDED.weight
                   RETURNING id""",
                uuid.UUID(src_entity_id), uuid.UUID(dst_entity_id), relation, weight,
            )
        return str(row["id"]) if row else None
    except Exception as e:
        logger.warning(f"life_graph.add_edge failed (fail-closed): {e}")
        return None


# ── Reads / traversal ─────────────────────────────────────────────────────────

async def get_entity(entity_id: str) -> Optional[dict]:
    """Fetch a single entity by id. Returns a dict (no embedding) or None."""
    if not graph_enabled():
        return None
    try:
        async with acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, type, name, description, created_at, updated_at
                   FROM entities WHERE id = $1""",
                uuid.UUID(entity_id),
            )
        return _entity_row(row) if row else None
    except Exception as e:
        logger.warning(f"life_graph.get_entity failed (fail-closed): {e}")
        return None


async def neighbors(entity_id: str, depth: int = 1) -> list[dict]:
    """Return entities reachable from ``entity_id`` within ``depth`` hops.

    Edges are walked in BOTH directions (an edge a->b makes a and b neighbours), so
    this answers "everything connected to X". The starting entity is never included.
    Each result carries the hop ``distance`` at which it was first reached. Returns []
    on any error or when the flag is OFF.
    """
    if not graph_enabled():
        return []
    if depth < 1:
        return []
    try:
        start = uuid.UUID(entity_id)
        visited: set[uuid.UUID] = {start}
        frontier: set[uuid.UUID] = {start}
        ordered: list[tuple[uuid.UUID, int]] = []  # (id, distance) in discovery order

        async with acquire() as conn:
            for hop in range(1, depth + 1):
                if not frontier:
                    break
                rows = await conn.fetch(
                    """SELECT src_entity_id, dst_entity_id FROM edges
                       WHERE src_entity_id = ANY($1::uuid[])
                          OR dst_entity_id = ANY($1::uuid[])""",
                    list(frontier),
                )
                next_frontier: set[uuid.UUID] = set()
                for r in rows:
                    for nid in (r["src_entity_id"], r["dst_entity_id"]):
                        if nid not in visited:
                            visited.add(nid)
                            next_frontier.add(nid)
                            ordered.append((nid, hop))
                frontier = next_frontier

            if not ordered:
                return []

            ids = [nid for nid, _ in ordered]
            ent_rows = await conn.fetch(
                """SELECT id, type, name, description, created_at, updated_at
                   FROM entities WHERE id = ANY($1::uuid[])""",
                ids,
            )

        by_id = {row["id"]: _entity_row(row) for row in ent_rows}
        out: list[dict] = []
        for nid, dist in ordered:
            ent = by_id.get(nid)
            if ent:
                out.append({**ent, "distance": dist})
        return out
    except Exception as e:
        logger.warning(f"life_graph.neighbors failed (fail-closed): {e}")
        return []


async def hybrid_lookup(query: str, *, top_k: int = 5) -> list[dict]:
    """Vector-match entity descriptions to ``query``, then expand each by 1 hop.

    Returns the matched entities (each with a ``similarity`` and a ``neighbors`` list
    of directly-connected entities). This is the structured analogue of memory recall:
    the vector store finds the relevant entity, the graph supplies its context.
    Returns [] on any error or when the flag is OFF.
    """
    if not graph_enabled():
        return []
    if not (query or "").strip():
        return []
    try:
        vector_str = _vector_literal(await embed_one(query))
        async with acquire() as conn:
            matches = await conn.fetch(
                """SELECT id, type, name, description, created_at, updated_at,
                          1 - (embedding <=> $1::vector) AS similarity
                   FROM entities
                   WHERE embedding IS NOT NULL
                   ORDER BY embedding <=> $1::vector
                   LIMIT $2""",
                vector_str, top_k,
            )
    except Exception as e:
        logger.warning(f"life_graph.hybrid_lookup match failed (fail-closed): {e}")
        return []

    results: list[dict] = []
    for m in matches:
        ent = _entity_row(m)
        ent["similarity"] = float(m["similarity"])
        # 1-hop expansion; neighbors() is itself fail-closed (returns [] on error).
        ent["neighbors"] = await neighbors(str(m["id"]), depth=1)
        results.append(ent)
    return results


# ── helpers ───────────────────────────────────────────────────────────────────

def _entity_row(row) -> dict:
    """Project an entities row into a plain dict (embedding intentionally omitted)."""
    return {
        "id": str(row["id"]),
        "type": row["type"],
        "name": row["name"],
        "description": row["description"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }
