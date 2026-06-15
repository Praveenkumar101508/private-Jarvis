"""Task management endpoints — IRA's to-do and reminder system."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.middleware.auth import require_auth
from tasks.manager import (
    create_task, get_task, list_tasks, update_task,
    complete_task, get_overdue_tasks,
)
from worker.reminders import create_reminder

router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskCreate(BaseModel):
    title: str
    description: str | None = None
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    due_at: datetime | None = None
    tags: list[str] = []
    remind_at: datetime | None = None


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    priority: Literal["low", "medium", "high", "urgent"] | None = None
    status: Literal["pending", "in_progress", "done", "cancelled"] | None = None
    due_at: datetime | None = None
    tags: list[str] | None = None


class ReminderCreate(BaseModel):
    title: str
    remind_at: datetime
    body: str | None = None
    task_id: str | None = None
    channels: list[str] = ["websocket"]
    repeat_cron: str | None = None


@router.post("", status_code=201)
async def create(body: TaskCreate, _user: str = Depends(require_auth)):
    return await create_task(
        body.title,
        description=body.description,
        priority=body.priority,
        due_at=body.due_at,
        tags=body.tags,
        remind_at=body.remind_at,
    )


@router.get("")
async def list_all(
    status: str | None = Query(None),
    priority: str | None = Query(None),
    limit: int = Query(50, le=200),
    _user: str = Depends(require_auth),
):
    return await list_tasks(status=status, priority=priority, limit=limit)


@router.get("/overdue")
async def overdue(_user: str = Depends(require_auth)):
    return await get_overdue_tasks()


@router.get("/{task_id}")
async def get_one(task_id: str, _user: str = Depends(require_auth)):
    task = await get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.patch("/{task_id}")
async def update_one(task_id: str, body: TaskUpdate, _user: str = Depends(require_auth)):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    return await update_task(task_id, **updates)


@router.post("/{task_id}/complete")
async def complete(task_id: str, _user: str = Depends(require_auth)):
    task = await complete_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/reminders", status_code=201)
async def add_reminder(body: ReminderCreate, _user: str = Depends(require_auth)):
    rem_id = await create_reminder(
        title=body.title,
        remind_at=body.remind_at,
        body=body.body,
        task_id=body.task_id,
        channels=body.channels,
        repeat_cron=body.repeat_cron,
    )
    return {"id": rem_id, "status": "created"}
