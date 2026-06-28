"""Feature 1 — Life Context Graph tests.

Covers: flag-OFF no-op (no DB touched), entity upsert, edge add, neighbors traversal
(both directions, multi-hop), hybrid_lookup, and fail-closed behaviour on DB errors.
The DB and the BGE embedder are mocked, so no Postgres / model is required.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD",
           "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

import memory.life_graph as lg


# ── Fake DB plumbing (mirrors tests/test_security_events.py) ──────────────────

class _FakeConn:
    def __init__(self, *, fetchrow_rows=None, fetch_rows=None):
        # fetchrow_rows / fetch_rows are queues of return values, consumed in order.
        self._fetchrow = list(fetchrow_rows or [])
        self._fetch = list(fetch_rows or [])
        self.calls: list[tuple] = []

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        return self._fetchrow.pop(0) if self._fetchrow else None

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        return self._fetch.pop(0) if self._fetch else []


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *_):
        pass


def _enable(monkeypatch):
    monkeypatch.setenv("IRA_LIFE_GRAPH", "true")


async def _fake_embed(_text):
    return [0.0] * 1024


# ── Flag gate ─────────────────────────────────────────────────────────────────

def test_flag_defaults_off(monkeypatch):
    monkeypatch.delenv("IRA_LIFE_GRAPH", raising=False)
    assert lg.graph_enabled() is False


@pytest.mark.asyncio
async def test_flag_off_is_noop_and_never_touches_db(monkeypatch):
    monkeypatch.delenv("IRA_LIFE_GRAPH", raising=False)
    # acquire is patched to explode — proving the flag-OFF path never calls it.
    with patch("memory.life_graph.acquire", side_effect=AssertionError("DB touched!")):
        assert await lg.upsert_entity("project", "Lux") is None
        assert await lg.add_edge("a", "b", "rel") is None
        assert await lg.get_entity("x") is None
        assert await lg.neighbors("x") == []
        assert await lg.hybrid_lookup("anything") == []


# ── Entity upsert ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upsert_entity_returns_id_and_embeds(monkeypatch):
    _enable(monkeypatch)
    eid = "11111111-1111-1111-1111-111111111111"
    conn = _FakeConn(fetchrow_rows=[{"id": eid}])
    with patch("memory.life_graph.acquire", return_value=_FakeAcquire(conn)), \
         patch("memory.life_graph.embed_one", _fake_embed):
        out = await lg.upsert_entity("application", "Luxembourg PhD",
                                     description="EU doctoral application")
    assert out == eid
    _, sql, args = conn.calls[0]
    assert "INSERT INTO entities" in sql and "ON CONFLICT (type, name)" in sql
    # description present → embedding literal passed (not None)
    assert args[3] is not None and args[3].startswith("[")


@pytest.mark.asyncio
async def test_upsert_entity_without_description_skips_embedding(monkeypatch):
    _enable(monkeypatch)
    conn = _FakeConn(fetchrow_rows=[{"id": "22222222-2222-2222-2222-222222222222"}])
    # embed_one must NOT be called when there is no description.
    def _boom(_):
        raise AssertionError("embed called with no description")
    with patch("memory.life_graph.acquire", return_value=_FakeAcquire(conn)), \
         patch("memory.life_graph.embed_one", _boom):
        out = await lg.upsert_entity("person", "Praveen")
    assert out is not None
    assert conn.calls[0][2][3] is None  # embedding arg is None


@pytest.mark.asyncio
async def test_upsert_entity_requires_type_and_name(monkeypatch):
    _enable(monkeypatch)
    with patch("memory.life_graph.acquire", side_effect=AssertionError("DB touched")):
        assert await lg.upsert_entity("", "x") is None
        assert await lg.upsert_entity("person", "") is None


# ── Edge add ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_add_edge_returns_id(monkeypatch):
    _enable(monkeypatch)
    a, b = "11111111-1111-1111-1111-111111111111", "33333333-3333-3333-3333-333333333333"
    conn = _FakeConn(fetchrow_rows=[{"id": "edge-1"}])
    with patch("memory.life_graph.acquire", return_value=_FakeAcquire(conn)):
        out = await lg.add_edge(a, b, "applies_to", weight=2.5)
    assert out == "edge-1"
    _, sql, args = conn.calls[0]
    assert "INSERT INTO edges" in sql and "ON CONFLICT" in sql
    assert args[2] == "applies_to" and args[3] == 2.5


# ── neighbors traversal ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_neighbors_one_hop_both_directions(monkeypatch):
    _enable(monkeypatch)
    a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # a -> b
    c = "cccccccc-cccc-cccc-cccc-cccccccccccc"  # c -> a (incoming)
    import uuid as _uuid
    ua, ub, uc = _uuid.UUID(a), _uuid.UUID(b), _uuid.UUID(c)
    # First fetch: edges touching {a}. Second fetch: entity rows for {b, c}.
    edge_rows = [{"src_entity_id": ua, "dst_entity_id": ub},
                 {"src_entity_id": uc, "dst_entity_id": ua}]
    ent_rows = [
        {"id": ub, "type": "project", "name": "B", "description": None,
         "created_at": None, "updated_at": None},
        {"id": uc, "type": "person", "name": "C", "description": None,
         "created_at": None, "updated_at": None},
    ]
    conn = _FakeConn(fetch_rows=[edge_rows, ent_rows])
    with patch("memory.life_graph.acquire", return_value=_FakeAcquire(conn)):
        out = await lg.neighbors(a, depth=1)
    names = {n["name"] for n in out}
    assert names == {"B", "C"}            # both outgoing and incoming neighbours
    assert all(n["distance"] == 1 for n in out)
    assert a not in {n["id"] for n in out}  # start excluded


@pytest.mark.asyncio
async def test_neighbors_depth_two_expands(monkeypatch):
    _enable(monkeypatch)
    import uuid as _uuid
    a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    c = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    ua, ub, uc = _uuid.UUID(a), _uuid.UUID(b), _uuid.UUID(c)
    hop1 = [{"src_entity_id": ua, "dst_entity_id": ub}]        # a-b
    hop2 = [{"src_entity_id": ub, "dst_entity_id": uc}]        # b-c
    ent_rows = [
        {"id": ub, "type": "t", "name": "B", "description": None,
         "created_at": None, "updated_at": None},
        {"id": uc, "type": "t", "name": "C", "description": None,
         "created_at": None, "updated_at": None},
    ]
    conn = _FakeConn(fetch_rows=[hop1, hop2, ent_rows])
    with patch("memory.life_graph.acquire", return_value=_FakeAcquire(conn)):
        out = await lg.neighbors(a, depth=2)
    by_name = {n["name"]: n["distance"] for n in out}
    assert by_name == {"B": 1, "C": 2}


@pytest.mark.asyncio
async def test_neighbors_no_edges_returns_empty(monkeypatch):
    _enable(monkeypatch)
    conn = _FakeConn(fetch_rows=[[]])  # no edges
    with patch("memory.life_graph.acquire", return_value=_FakeAcquire(conn)):
        assert await lg.neighbors("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa") == []


# ── hybrid_lookup ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_hybrid_lookup_matches_and_expands(monkeypatch):
    _enable(monkeypatch)
    import uuid as _uuid
    a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    ua, ub = _uuid.UUID(a), _uuid.UUID(b)
    match_rows = [{"id": ua, "type": "application", "name": "Luxembourg PhD",
                   "description": "EU app", "created_at": None, "updated_at": None,
                   "similarity": 0.91}]
    # neighbors() for the match: one edge a-b, then entity row for b.
    edge_rows = [{"src_entity_id": ua, "dst_entity_id": ub}]
    ent_rows = [{"id": ub, "type": "document", "name": "CV", "description": None,
                 "created_at": None, "updated_at": None}]
    conn = _FakeConn(fetch_rows=[match_rows, edge_rows, ent_rows])
    with patch("memory.life_graph.acquire", return_value=_FakeAcquire(conn)), \
         patch("memory.life_graph.embed_one", _fake_embed):
        out = await lg.hybrid_lookup("luxembourg")
    assert len(out) == 1
    assert out[0]["name"] == "Luxembourg PhD"
    assert out[0]["similarity"] == pytest.approx(0.91)
    assert [n["name"] for n in out[0]["neighbors"]] == ["CV"]


# ── fail-closed ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_db_error_fails_closed(monkeypatch):
    _enable(monkeypatch)
    with patch("memory.life_graph.acquire", side_effect=RuntimeError("DB down")), \
         patch("memory.life_graph.embed_one", _fake_embed):
        assert await lg.upsert_entity("p", "n", description="d") is None
        assert await lg.add_edge("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                                 "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "r") is None
        assert await lg.get_entity("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa") is None
        assert await lg.neighbors("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa") == []
        assert await lg.hybrid_lookup("q") == []
