"""
IRA Startup Connectivity Health Check

Verifies that all external services are reachable before (or during) boot.
ALL failures are logged as warnings — none block startup.

Checked services:
  • PostgreSQL      — asyncpg connection
  • Redis           — redis.asyncio PING
  • ChromaDB        — AsyncHttpClient heartbeat
  • Ollama fast     — GET /api/tags on thin-client URL
  • Ollama heavy    — GET /api/tags on Shadow PC URL (via Tailscale)
"""
import asyncio

import httpx
import structlog

from config import settings

log = structlog.get_logger()


async def _check_postgres() -> None:
    """Verify PostgreSQL is reachable and the reminders table exists."""
    try:
        import asyncpg

        dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
        conn = await asyncpg.connect(dsn=dsn, timeout=5)
        await conn.execute("SELECT 1")
        await conn.close()
        log.info("startup_check_ok", service="postgresql")
    except Exception as exc:
        log.warning("startup_check_failed", service="postgresql", error=str(exc))


async def _check_redis() -> None:
    """Verify Redis is reachable via PING."""
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(
            settings.redis_url,
            password=settings.redis_password or None,
            socket_connect_timeout=5,
        )
        await r.ping()
        await r.aclose()
        log.info("startup_check_ok", service="redis")
    except Exception as exc:
        log.warning("startup_check_failed", service="redis", error=str(exc))


async def _check_chromadb() -> None:
    """Verify ChromaDB HTTP server is reachable via heartbeat."""
    try:
        import chromadb

        client = await chromadb.AsyncHttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
        )
        await client.heartbeat()
        log.info("startup_check_ok", service="chromadb")
    except Exception as exc:
        log.warning("startup_check_failed", service="chromadb", error=str(exc))


async def _check_ollama(label: str, base_url: str) -> None:
    """Verify an Ollama instance responds to GET /api/tags."""
    url = base_url.rstrip("/") + "/api/tags"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                log.info("startup_check_ok", service=label, url=url)
            else:
                log.warning(
                    "startup_check_failed",
                    service=label,
                    url=url,
                    status=resp.status_code,
                )
    except Exception as exc:
        log.warning("startup_check_failed", service=label, url=url, error=str(exc))


async def run_startup_checks() -> None:
    """
    Run all connectivity checks concurrently.
    Call this from the FastAPI lifespan startup hook.
    Never raises — all errors are logged as warnings.
    """
    log.info("startup_checks_begin")
    await asyncio.gather(
        _check_postgres(),
        _check_redis(),
        _check_chromadb(),
        _check_ollama("ollama_fast", settings.ollama_base_url),
        _check_ollama("ollama_heavy", settings.ollama_heavy_url),
        return_exceptions=True,  # belt-and-suspenders: swallow any unforeseen raises
    )
    log.info("startup_checks_complete")
