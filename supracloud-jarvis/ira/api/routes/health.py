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
            r = await client.get(f"{url.removesuffix('/v1')}/health",
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
        version=cfg.ira_version,
        services={
            "postgres":  pg,
            "redis":     rd,
            "vllm_fast": fast,
            "vllm_deep": deep,
        },
    )


# ── Per-pillar detail (5.3) ───────────────────────────────────────────────────
# Reports each subsystem independently and NEVER raises — every probe degrades to
# a status instead of throwing, so one subsystem being down doesn't break /health
# (and, by the same fail-soft design across the request paths, doesn't break chat).

async def _check_ollama(base_url: str) -> ServiceStatus:
    t = time.monotonic()
    root = base_url.removesuffix("/v1")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{root}/api/tags")
        return ServiceStatus(status="ok" if r.status_code == 200 else "degraded",
                             latency_ms=int((time.monotonic() - t) * 1000))
    except Exception:
        return ServiceStatus(status="down", latency_ms=0)


async def _check_hermes() -> ServiceStatus:
    import os
    enabled = os.getenv("IRA_USE_HERMES", "false").strip().lower() in ("1", "true", "yes", "on")
    if not enabled:
        return ServiceStatus(status="degraded", latency_ms=0)  # off — legacy engine active
    url = os.getenv("IRA_HERMES_URL", "http://127.0.0.1:8642/v1").rstrip("/")
    key = os.getenv("IRA_HERMES_KEY", "")
    t = time.monotonic()
    try:
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{url}/models", headers=headers)
        return ServiceStatus(status="ok" if r.status_code == 200 else "degraded",
                             latency_ms=int((time.monotonic() - t) * 1000))
    except Exception:
        return ServiceStatus(status="down", latency_ms=0)


def _norm(result) -> dict:
    """Normalize a ServiceStatus / leaked exception into a plain status dict."""
    if isinstance(result, ServiceStatus):
        return {"status": result.status, "latency_ms": result.latency_ms}
    return {"status": "down", "latency_ms": 0}


@router.get("/health/detail")
async def health_detail():
    """Independent status for each pillar/subsystem. Always 200; never raises."""
    cfg = get_settings()

    pg, rd, brain, hermes = await asyncio.gather(
        _check_postgres(), _check_redis(),
        _check_ollama(getattr(cfg, "ollama_base_url", "http://localhost:11434/v1")),
        _check_hermes(),
        return_exceptions=True,
    )

    # Web-research channels + action deps — both already fail soft.
    try:
        import channels
        research = await channels.doctor()
    except Exception as exc:  # noqa: BLE001
        research = {"error": str(exc)[:80]}
    try:
        from actions import action_status
        actions = action_status(cfg)
    except Exception as exc:  # noqa: BLE001
        actions = {"error": str(exc)[:80]}

    try:
        from utils.llm import vision_available
        vision_ok = vision_available()
    except Exception:
        vision_ok = False

    pillars = {
        "brain": {"ollama": _norm(brain), "hermes": _norm(hermes)},
        "memory": {"postgres": _norm(pg), "redis": _norm(rd),
                   "embedding_model": getattr(cfg, "embedding_model", "")},
        "vision": {"configured": bool(vision_ok),
                   "model": getattr(cfg, "ollama_vision_model", "")},
        "voice": {"configured": bool(getattr(cfg, "livekit_api_key", "")),
                  "note": "voice runs as a separate service; config presence only"},
        "web_research": research,
        "actions": actions,
    }

    mem_ok = _norm(pg)["status"] == "ok" and _norm(rd)["status"] == "ok"
    brain_ok = _norm(brain)["status"] == "ok" or _norm(hermes)["status"] == "ok"
    overall = "ok" if (mem_ok and brain_ok) else ("degraded" if (mem_ok or brain_ok) else "down")

    return {"status": overall, "version": cfg.ira_version, "pillars": pillars}
