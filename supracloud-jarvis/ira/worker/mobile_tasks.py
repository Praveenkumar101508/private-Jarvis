"""worker/mobile_tasks.py — execute-ASAP task queue for the mobile app (#3).

A task is submitted from the phone, runs ASAP in the background, and the result is
fetchable + a push fires on completion. Side-effecting task types (send, delete,
schedule, outbound) are routed through the EXISTING approval gate
(utils.approval.owner_gated_action), so a phone tap can NEVER silently fire an
outbound action — it returns a confirmation request the owner must approve first.

Task state is kept in-process, matching the single-process native deployment (the
same choice utils/approval.py documents); swap for Redis/Postgres if scaled out.
Everything is owner-gated and fail-soft.

Task types are pluggable via register_runner(); one real, gated runner ("email",
reusing utils.email_send) ships so the endpoint is concretely useful and exercises
the gate end-to-end.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from utils.approval import owner_gated_action

logger = logging.getLogger("ira.mobile.tasks")

Runner = Callable[[dict], Awaitable[Any]]
PreviewFn = Callable[[dict], str]

_MAX_TASKS = 200
_PUBLIC_FIELDS = ("id", "type", "status", "result", "error", "created")


@dataclass
class RunnerSpec:
    fn: Runner
    side_effecting: bool = False
    preview: Optional[PreviewFn] = None


_RUNNERS: dict[str, RunnerSpec] = {}
_TASKS: dict[str, dict] = {}
_HANDLES: dict[str, asyncio.Task] = {}


def register_runner(name: str, fn: Runner, *, side_effecting: bool = False,
                    preview: Optional[PreviewFn] = None) -> None:
    _RUNNERS[name] = RunnerSpec(fn=fn, side_effecting=side_effecting, preview=preview)


def _public(rec: dict) -> dict:
    return {k: rec[k] for k in _PUBLIC_FIELDS}


def _evict_old() -> None:
    if len(_TASKS) <= _MAX_TASKS:
        return
    for tid in sorted(_TASKS, key=lambda t: _TASKS[t]["created"])[:len(_TASKS) - _MAX_TASKS]:
        _TASKS.pop(tid, None)
        _HANDLES.pop(tid, None)


def _enqueue(task_type: str, params: dict, fn: Runner) -> dict:
    """Create a task record and kick off its background run. Returns the public record."""
    tid = uuid.uuid4().hex
    rec = {"id": tid, "type": task_type, "status": "queued", "result": None,
           "error": None, "created": time.time()}
    _TASKS[tid] = rec
    _evict_old()
    _HANDLES[tid] = asyncio.create_task(_run(tid, params, fn))
    return _public(rec)


async def _run(tid: str, params: dict, fn: Runner) -> None:
    rec = _TASKS.get(tid)
    if rec is None:
        return
    rec["status"] = "running"
    try:
        rec["result"] = await fn(params)
        rec["status"] = "done"
    except Exception as exc:  # noqa: BLE001 - a failed task must not crash the worker
        rec["status"] = "failed"
        rec["error"] = str(exc)[:500]
        logger.warning("mobile task %s (%s) failed: %s", tid, rec["type"], exc)
    await _notify_done(rec)


async def _notify_done(rec: dict) -> None:
    """Push the result to the phone (fail-soft; no-op if push is disabled)."""
    try:
        from worker.push_mobile import send_push
        await send_push(
            f"Task {rec['status']}", f"{rec['type']} — {rec['status']}",
            priority="info", data={"task_id": rec["id"], "type": rec["type"]})
    except Exception as exc:  # noqa: BLE001
        logger.debug("mobile task completion push failed (non-fatal): %s", exc)


async def submit_task(owner: str, task_type: str, params: dict, *,
                      confirm_token: Optional[str] = None, is_owner: bool = False) -> dict:
    """Submit a task to run ASAP. Owner-gated; side-effecting types pass through the
    approval gate (confirmation_required until the owner confirms)."""
    if not is_owner:
        return {"status": "forbidden", "detail": "Tasks are restricted to the verified owner."}
    spec = _RUNNERS.get(task_type)
    if spec is None:
        return {"status": "unknown_task", "task_type": task_type}

    if spec.side_effecting:
        preview = spec.preview(params) if spec.preview else f"Run task '{task_type}'"
        outcome = await owner_gated_action(
            owner_username=owner, is_owner=is_owner, action=task_type, preview=preview,
            execute=lambda: _enqueue(task_type, params, spec.fn),  # runs ASAP only on confirm
            confirm_token=confirm_token,
        )
        if outcome["status"] == "executed":
            return {"status": "queued", "task": outcome["result"]}
        return outcome   # confirmation_required / expired / not_found / forbidden

    return {"status": "queued", "task": _enqueue(task_type, params, spec.fn)}


def get_task(task_id: str) -> Optional[dict]:
    rec = _TASKS.get(task_id)
    return _public(rec) if rec else None


def list_tasks(limit: int = 20) -> list[dict]:
    recs = sorted(_TASKS.values(), key=lambda r: r["created"], reverse=True)
    return [_public(r) for r in recs[:max(1, min(limit, _MAX_TASKS))]]


async def wait_for(task_id: str) -> None:
    """Await a task's background completion (used by tests / callers that need the result)."""
    handle = _HANDLES.get(task_id)
    if handle is not None:
        await asyncio.gather(handle, return_exceptions=True)


# ── Built-in task types ───────────────────────────────────────────────────────

def _email_preview(params: dict) -> str:
    return (f"Send email to {params.get('to')}\nSubject: {params.get('subject')}\n\n"
            f"{params.get('body', '')}")


async def _email_runner(params: dict) -> Any:
    from utils.email_send import send_email   # fail-soft; returns a status dict

    return await send_email(to=params.get("to"), subject=params.get("subject"),
                            body=params.get("body"))


register_runner("email", _email_runner, side_effecting=True, preview=_email_preview)


__all__ = [
    "register_runner", "submit_task", "get_task", "list_tasks", "wait_for", "RunnerSpec",
]
