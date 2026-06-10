"""Prompt 5.3 — per-pillar /health/detail reports each subsystem independently.

The endpoint must NEVER raise: one subsystem being down still returns a status for
every pillar (the same fail-soft design that keeps chat working when a subsystem
is unavailable).
"""
import os

for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

import asyncio
from unittest.mock import AsyncMock

import api.routes.health as hmod
from api.routes.health import health_detail, ServiceStatus


class _Cfg:
    ira_version = "1.0.0"
    ollama_base_url = "http://localhost:11434/v1"
    embedding_model = "BAAI/bge-large-en-v1.5"
    ollama_vision_model = "qwen2.5vl"
    livekit_api_key = ""
    calcom_api_key = ""
    smtp_host = ""


def _patch_probes(monkeypatch, *, pg, rd, ollama, hermes):
    monkeypatch.setattr(hmod, "get_settings", lambda: _Cfg())
    monkeypatch.setattr(hmod, "_check_postgres", AsyncMock(return_value=ServiceStatus(status=pg, latency_ms=1)))
    monkeypatch.setattr(hmod, "_check_redis", AsyncMock(return_value=ServiceStatus(status=rd, latency_ms=1)))
    monkeypatch.setattr(hmod, "_check_ollama", AsyncMock(return_value=ServiceStatus(status=ollama, latency_ms=1)))
    monkeypatch.setattr(hmod, "_check_hermes", AsyncMock(return_value=ServiceStatus(status=hermes, latency_ms=1)))
    monkeypatch.setattr("channels.doctor", AsyncMock(return_value={"search": {"ok": False, "detail": "down"}}))


def test_detail_reports_all_pillars_with_one_subsystem_down(monkeypatch):
    _patch_probes(monkeypatch, pg="down", rd="ok", ollama="ok", hermes="degraded")
    out = asyncio.run(health_detail())

    assert set(out["pillars"]) == {"brain", "memory", "vision", "voice", "web_research", "actions"}
    # Independence: postgres down, but redis + brain still reported.
    assert out["pillars"]["memory"]["postgres"]["status"] == "down"
    assert out["pillars"]["memory"]["redis"]["status"] == "ok"
    assert out["pillars"]["brain"]["ollama"]["status"] == "ok"
    # Action deps unconfigured -> reported, not crashed.
    assert out["pillars"]["actions"]["calendar"]["configured"] is False
    assert out["status"] in ("ok", "degraded", "down")


def test_detail_all_down_is_down_and_still_returns_every_pillar(monkeypatch):
    _patch_probes(monkeypatch, pg="down", rd="down", ollama="down", hermes="down")
    out = asyncio.run(health_detail())
    assert out["status"] == "down"
    assert "web_research" in out["pillars"]   # never raised even with everything down


def test_detail_healthy_core_is_ok(monkeypatch):
    _patch_probes(monkeypatch, pg="ok", rd="ok", ollama="ok", hermes="ok")
    out = asyncio.run(health_detail())
    assert out["status"] == "ok"
