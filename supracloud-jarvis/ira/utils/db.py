"""Async PostgreSQL connection pool via asyncpg."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import asyncpg

from config import get_settings

_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    global _pool
    cfg = get_settings()
    _pool = await asyncpg.create_pool(
        dsn=cfg.database_dsn,
        min_size=5,
        max_size=20,
        command_timeout=30,
        max_inactive_connection_lifetime=300,
    )


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool not initialised. Call init_pool() first.")
    return _pool


@asynccontextmanager
async def acquire() -> AsyncGenerator[asyncpg.Connection, None]:
    """Context manager that acquires and releases a connection from the pool."""
    async with get_pool().acquire() as conn:
        yield conn
