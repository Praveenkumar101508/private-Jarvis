"""Business-data tenant isolation (Phase 5) — proves no cross-tenant reads.

Uses a FakeConn (a minimal tenant-aware stand-in for asyncpg.Connection) so the
isolation guarantee is tested without a live Postgres. Async ops are driven via
asyncio.run, so no pytest-asyncio dependency.
"""
import asyncio
import uuid

import data  # ira/ is on sys.path (pytest rootdir)
from data import (
    add_client_agent,
    add_investor,
    list_client_agents,
    list_investors,
    session_key_for_tenant,
)


class FakeConn:
    """Understands this module's query shapes: INSERT ... RETURNING id and
    SELECT ... WHERE tenant_id = $1::uuid. Stores rows by tenant and filters on read."""

    def __init__(self):
        self.store = {"investors": [], "client_agents": []}

    async def fetchrow(self, sql, *args):
        rid = str(uuid.uuid4())
        if "INSERT INTO investors" in sql:
            self.store["investors"].append({"id": rid, "tenant_id": args[0], "name": args[1]})
        elif "INSERT INTO client_agents" in sql:
            self.store["client_agents"].append({"id": rid, "tenant_id": args[0], "client_name": args[1]})
        return {"id": rid}

    async def fetch(self, sql, *args):
        tid = args[0]
        table = "investors" if "FROM investors" in sql else "client_agents"
        # Mirror the WHERE tenant_id = $1 filter the access layer relies on.
        return [r for r in self.store[table] if r["tenant_id"] == tid]


def test_session_key_for_tenant():
    assert session_key_for_tenant("abc") == "tenant:abc"
    assert session_key_for_tenant("A") != session_key_for_tenant("B")


def test_no_cross_tenant_reads():
    async def _run():
        fc = FakeConn()
        await add_investor("tenant-A", "Alice", conn=fc)
        await add_investor("tenant-A", "Alex", conn=fc)
        await add_investor("tenant-B", "Bob", conn=fc)
        await add_client_agent("tenant-A", "ClientA", conn=fc)
        await add_client_agent("tenant-B", "ClientB", conn=fc)

        a_inv = await list_investors("tenant-A", conn=fc)
        b_inv = await list_investors("tenant-B", conn=fc)
        a_ca = await list_client_agents("tenant-A", conn=fc)
        b_ca = await list_client_agents("tenant-B", conn=fc)
        return a_inv, b_inv, a_ca, b_ca

    a_inv, b_inv, a_ca, b_ca = asyncio.run(_run())

    assert {r["name"] for r in a_inv} == {"Alice", "Alex"}
    assert {r["name"] for r in b_inv} == {"Bob"}
    # B must NOT see any of A's rows, and vice-versa
    assert all(r["tenant_id"] == "tenant-B" for r in b_inv)
    assert all(r["tenant_id"] == "tenant-A" for r in a_inv)
    assert {r["client_name"] for r in a_ca} == {"ClientA"}
    assert {r["client_name"] for r in b_ca} == {"ClientB"}


def test_every_read_is_tenant_scoped():
    # Structural guarantee: the access-layer SELECTs filter by tenant_id.
    import inspect

    src = inspect.getsource(data)
    for select in ("FROM investors", "FROM client_agents"):
        idx = src.index(select)
        snippet = src[idx: idx + 120]
        assert "tenant_id = $1::uuid" in snippet, f"{select} read not tenant-scoped"
