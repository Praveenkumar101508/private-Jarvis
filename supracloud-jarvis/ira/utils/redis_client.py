"""Async Redis client — caching, rate limiting, pub/sub."""

import json
from typing import Any

import redis.asyncio as aioredis

from config import get_settings

_redis: aioredis.Redis | None = None


async def init_redis() -> None:
    global _redis
    cfg = get_settings()
    _redis = aioredis.from_url(
        cfg.redis_url,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=5,
        socket_keepalive=True,
    )
    await _redis.ping()


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


def get_redis() -> aioredis.Redis:
    if _redis is None:
        raise RuntimeError("Redis not initialised. Call init_redis() first.")
    return _redis


async def cache_get(key: str) -> Any | None:
    value = await get_redis().get(key)
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


async def cache_set(key: str, value: Any, ttl: int = 300) -> None:
    serialised = json.dumps(value) if not isinstance(value, str) else value
    await get_redis().setex(key, ttl, serialised)


async def cache_delete(key: str) -> None:
    await get_redis().delete(key)


async def publish_event(channel: str, payload: dict) -> None:
    """Publish a proactive event (security alert, briefing, etc.)."""
    await get_redis().publish(channel, json.dumps(payload))
