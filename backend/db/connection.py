"""
Async PostgreSQL connection pool using asyncpg.

Usage:
    from db.connection import get_pool, close_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM reminders WHERE NOT notified")

    # On application shutdown:
    await close_pool()

Note: strips the SQLAlchemy "+asyncpg" driver prefix from DATABASE_URL before
      passing to asyncpg.create_pool, e.g.:
        postgresql+asyncpg://user:pass@host/db  →  postgresql://user:pass@host/db
"""
import asyncpg
import structlog

from config import settings

log = structlog.get_logger()

_pool: asyncpg.Pool | None = None


def _normalize_dsn(url: str) -> str:
    """Strip SQLAlchemy driver suffix so asyncpg can consume the DSN."""
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def get_pool() -> asyncpg.Pool:
    """Return the shared asyncpg pool, creating it on first call."""
    global _pool
    if _pool is None:
        dsn = _normalize_dsn(settings.database_url)
        _pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
        log.info("asyncpg_pool_created", dsn=dsn.split("@")[-1])  # log host/db only
    return _pool


async def close_pool() -> None:
    """Gracefully close the connection pool on shutdown."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        log.info("asyncpg_pool_closed")
