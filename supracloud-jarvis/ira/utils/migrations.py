"""
Schema migrations runner.  # Fix P22

Applies every postgres/*.sql file in sorted filename order that has not yet
been recorded in the schema_migrations table.  Each file runs in its own
transaction; on success the filename is recorded.  Safe to call on every boot.

Why this exists alongside docker-entrypoint-initdb.d mounts
------------------------------------------------------------
docker-entrypoint-initdb.d scripts run *only* on a brand-new data volume.
Existing installs never see 002/003/004, causing KeyError / missing-column
crashes after an upgrade.  This runner is the durable upgrade path.

The compose docker-entrypoint-initdb.d mounts are kept for first-boot speed
(Postgres runs them before we can connect) but are now considered redundant for
correctness — the runner guarantees all migrations are applied on every start.
"""
from __future__ import annotations

import logging
from pathlib import Path

import asyncpg

logger = logging.getLogger("ira.migrations")

# Resolved at import time; works in Docker (/app/postgres) and local dev.
# Mirrors the repo-root discovery used in utils/auto_implement.py.
_POSTGRES_DIR: Path = (Path(__file__).resolve().parent.parent.parent / "postgres").resolve()


async def run_migrations(pool: asyncpg.Pool) -> None:
    """Apply all pending *.sql migrations in sorted filename order.

    Idempotent and safe to call on every boot.  Each migration runs in its own
    transaction; already-applied migrations are skipped.
    """
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                name       TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )

    if not _POSTGRES_DIR.is_dir():
        logger.warning("migrations: postgres/ directory not found at %s — skipping", _POSTGRES_DIR)
        return

    sql_files = sorted(_POSTGRES_DIR.glob("*.sql"))
    if not sql_files:
        logger.info("migrations: no SQL files found in %s", _POSTGRES_DIR)
        return

    async with pool.acquire() as conn:
        applied: set[str] = {
            row["name"] for row in await conn.fetch("SELECT name FROM schema_migrations")
        }

    for sql_file in sql_files:
        name = sql_file.name
        if name in applied:
            logger.debug("migrations: %s already applied — skipping", name)
            continue

        sql = sql_file.read_text(encoding="utf-8")
        logger.info("migrations: applying %s …", name)
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (name) VALUES ($1) ON CONFLICT DO NOTHING",
                    name,
                )
        logger.info("migrations: %s applied successfully", name)

    logger.info("migrations: all pending migrations applied")
