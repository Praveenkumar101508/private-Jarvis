"""Health and status endpoints — always public, no auth required."""

from __future__ import annotations

import asyncio
import time

import httpx
import psutil
from fastapi import APIRouter
from pydantic import BaseModel

from config import get_settings
from utils.db import get_pool
from utils.redis_client import get_redis

router = APIRouter(tags=["health"])


class ServiceStatus(BaseModel):
    status: str        # "ok" | "degraded" | "down"
    latency_ms: int


class HealthResponse(BaseModel):
    status: str
    version: str
    services: dict[str, ServiceStatus]
    gpu_vram_used_mb: int | None = None


async def _check_postgres() -> ServiceStatus:
    t = time.monotonic()
    try:
        await get_pool().fetchval("SELECT 1")
        return ServiceStatus(status="ok", latency_ms=int((time.monotonic() - t) * 1000))
    except Exception:
        return ServiceStatus(status="down", latency_ms=0)


async def _check_redis() -> ServiceStatus:
    t = time.monotonic()
    try:
        await get_redis().ping()
        return ServiceStatus(status="ok", latency_ms=int((time.monotonic() - t) * 1000))
    except Exception:
        return ServiceStatus(status="down", latency_ms=0)


async def _check_vllm(url: str, api_key: str) -> ServiceStatus:
    t = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{url.rstrip('/v1')}/health",
                                 headers={"Authorization": f"Bearer {api_key}"})
        status = "ok" if r.status_code == 200 else "degraded"
        return ServiceStatus(status=status, latency_ms=int((time.monotonic() - t) * 1000))
    except Exception:
        return ServiceStatus(status="down", latency_ms=0)


@router.get("/health", response_model=HealthResponse)
async def health():
    cfg = get_settings()

    pg, rd, fast, deep = await asyncio.gather(
        _check_postgres(),
        _check_redis(),
        _check_vllm(cfg.vllm_fast_url, cfg.vllm_api_key),
        _check_vllm(cfg.vllm_deep_url, cfg.vllm_api_key),
    )

    all_ok = all(s.status == "ok" for s in [pg, rd, fast, deep])
    overall = "ok" if all_ok else ("degraded" if any(s.status == "ok" for s in [pg, rd]) else "down")

    return HealthResponse(
        status=overall,
        version=cfg.jarvis_version,
        services={
            "postgres":  pg,
            "redis":     rd,
            "vllm_fast": fast,
            "vllm_deep": deep,
        },
    )
