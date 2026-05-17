"""
Memory store — Redis for short-term, ChromaDB for long-term semantic memory
"""
import json
from datetime import datetime, timezone

import redis.asyncio as aioredis
import structlog

from config import settings

log = structlog.get_logger()

MAX_SHORT_TERM_TURNS = 20


class MemoryStore:
    def __init__(self):
        self._redis: aioredis.Redis | None = None

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(
                settings.redis_url,
                password=settings.redis_password or None,
                decode_responses=True,
            )
        return self._redis

    async def save_turn(self, session_id: str, user_msg: str, assistant_msg: str):
        r = await self._get_redis()
        key = f"ira:session:{session_id}:history"
        turn = json.dumps({
            "user": user_msg,
            "assistant": assistant_msg,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        await r.rpush(key, turn)
        await r.ltrim(key, -MAX_SHORT_TERM_TURNS, -1)
        await r.expire(key, 86400 * 7)  # 7 days TTL

    async def get_context(self, session_id: str, last_n: int = 10) -> str:
        try:
            r = await self._get_redis()
            key = f"ira:session:{session_id}:history"
            raw = await r.lrange(key, -last_n, -1)
            if not raw:
                return ""
            turns = [json.loads(t) for t in raw]
            lines = []
            for t in turns:
                lines.append(f"User: {t['user']}")
                lines.append(f"IRA: {t['assistant']}")
            return "\n".join(lines)
        except Exception as exc:
            log.warning("memory_load_failed", error=str(exc))
            return ""

    async def clear_session(self, session_id: str):
        r = await self._get_redis()
        await r.delete(f"ira:session:{session_id}:history")

    async def save_user_preference(self, user_id: str, key: str, value: str):
        r = await self._get_redis()
        await r.hset(f"ira:user:{user_id}:prefs", key, value)

    async def get_user_preferences(self, user_id: str) -> dict:
        try:
            r = await self._get_redis()
            return await r.hgetall(f"ira:user:{user_id}:prefs")
        except Exception:
            return {}
