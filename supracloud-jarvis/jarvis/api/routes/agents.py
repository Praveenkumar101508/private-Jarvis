"""
Agent management endpoints.

GET  /agents           → list all created agents
GET  /agents/{name}    → get a specific agent's code and config
POST /agents/create    → trigger the Meta Agent Creator directly
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.middleware.auth import require_auth
from utils.db import acquire

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentSummary(BaseModel):
    name: str
    description: str | None
    status: str
    created_at: str


class AgentDetail(BaseModel):
    name: str
    description: str | None
    code: str | None
    docker_config: str | None
    status: str
    created_at: str


@router.get("", response_model=list[AgentSummary])
async def list_agents(_user: str = Depends(require_auth)):
    async with acquire() as conn:
        rows = await conn.fetch(
            "SELECT name, description, status, created_at FROM agents ORDER BY created_at DESC"
        )
    return [
        AgentSummary(
            name=r["name"],
            description=r["description"],
            status=r["status"],
            created_at=r["created_at"].isoformat(),
        )
        for r in rows
    ]


@router.get("/{name}", response_model=AgentDetail)
async def get_agent(name: str, _user: str = Depends(require_auth)):
    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT name, description, code, docker_config, status, created_at FROM agents WHERE name=$1",
            name,
        )
    if not row:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    return AgentDetail(
        name=row["name"],
        description=row["description"],
        code=row["code"],
        docker_config=row["docker_config"],
        status=row["status"],
        created_at=row["created_at"].isoformat(),
    )
