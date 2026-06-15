"""
ira/data/ — multi-tenant business-data access layer (Phase 5).

Postgres holds BUSINESS DATA ONLY (investor outreach, client->agent specs); memory/recall
belongs to Cortex. Schema: postgres/008_business_data.sql (tenants, investors, client_agents).

TENANT ISOLATION (no cross-tenant reads):
  - PRIMARY guard: every query is scoped with `WHERE tenant_id = $1::uuid`. There is no
    function that reads across tenants.
  - Defense-in-depth: each DB op runs in a transaction that SETs `app.tenant_id`, which the
    008 Row-Level-Security policies enforce (fail-closed when unset).
  - Cortex memory is isolated per tenant via the bridge's X-Cortex-Session-Key header —
    use session_key_for_tenant() when calling bridge.ask(..., session_key=...).

Every public function takes tenant_id first. `conn=` is for tests (inject a fake/real
connection); in production it is omitted and a tenant-scoped pooled connection is used.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Callable, Optional

# utils.db (asyncpg) is imported lazily inside the DB paths, so this module — and its
# isolation tests, which inject a fake connection — import without the DB driver present.


def session_key_for_tenant(tenant_id: str) -> str:
    """Per-tenant Cortex memory scope (value for the X-Cortex-Session-Key header)."""
    return f"tenant:{tenant_id}"


@asynccontextmanager
async def _tenant_conn(tenant_id: str):
    """Pooled connection in a transaction with app.tenant_id set (for RLS)."""
    from utils.db import acquire
    async with acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant_id))
            yield conn


async def _run(tenant_id: str, fn: Callable[[Any], Awaitable[Any]], *, conn: Optional[Any] = None) -> Any:
    """Run fn(conn) against an injected conn (tests) or a tenant-scoped pooled conn (prod)."""
    if conn is not None:
        return await fn(conn)
    async with _tenant_conn(tenant_id) as c:
        return await fn(c)


# ── Tenants ───────────────────────────────────────────────────────────────────

async def create_tenant(name: str, *, conn: Optional[Any] = None) -> str:
    sql = "INSERT INTO tenants (name) VALUES ($1) ON CONFLICT (name) DO UPDATE SET name=EXCLUDED.name RETURNING id"
    # tenant creation isn't tenant-scoped; use the injected/pooled conn directly
    if conn is not None:
        row = await conn.fetchrow(sql, name)
    else:
        from utils.db import acquire
        async with acquire() as c:
            row = await c.fetchrow(sql, name)
    return str(row["id"])


# ── Investors (tenant-scoped) ─────────────────────────────────────────────────

async def add_investor(
    tenant_id: str, name: str, *, firm: Optional[str] = None,
    stage: str = "prospect", notes: Optional[str] = None, conn: Optional[Any] = None,
) -> str:
    sql = ("INSERT INTO investors (tenant_id, name, firm, stage, notes) "
           "VALUES ($1::uuid, $2, $3, $4, $5) RETURNING id")
    row = await _run(tenant_id, lambda c: c.fetchrow(sql, str(tenant_id), name, firm, stage, notes), conn=conn)
    return str(row["id"])


async def list_investors(tenant_id: str, *, conn: Optional[Any] = None) -> list[dict]:
    sql = ("SELECT id, name, firm, stage, notes, created_at FROM investors "
           "WHERE tenant_id = $1::uuid ORDER BY created_at DESC")
    rows = await _run(tenant_id, lambda c: c.fetch(sql, str(tenant_id)), conn=conn)
    return [dict(r) for r in rows]


# ── Client -> agent specs (tenant-scoped) ─────────────────────────────────────

async def add_client_agent(
    tenant_id: str, client_name: str, *, spec: Optional[dict] = None,
    status: str = "draft", conn: Optional[Any] = None,
) -> str:
    sql = ("INSERT INTO client_agents (tenant_id, client_name, spec, status) "
           "VALUES ($1::uuid, $2, $3::jsonb, $4) RETURNING id")
    payload = json.dumps(spec or {})
    row = await _run(tenant_id, lambda c: c.fetchrow(sql, str(tenant_id), client_name, payload, status), conn=conn)
    return str(row["id"])


async def list_client_agents(tenant_id: str, *, conn: Optional[Any] = None) -> list[dict]:
    sql = ("SELECT id, client_name, spec, status, created_at FROM client_agents "
           "WHERE tenant_id = $1::uuid ORDER BY created_at DESC")
    rows = await _run(tenant_id, lambda c: c.fetch(sql, str(tenant_id)), conn=conn)
    return [dict(r) for r in rows]


__all__ = [
    "session_key_for_tenant", "create_tenant",
    "add_investor", "list_investors", "add_client_agent", "list_client_agents",
]
