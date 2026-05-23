"""
Real-time notification endpoints.

GET  /notifications           — list recent notifications (paginated)
POST /notifications/{id}/read — mark as read
DELETE /notifications/read    — clear all read notifications
WS   /ws/notifications        — WebSocket: real-time push stream

WebSocket protocol:
  Client connects:  ws://host/ws/notifications?token=<JWT>
  Server sends:     {"id":"...","category":"security","title":"...","body":"...","priority":"critical"}
  Client sends:     {"action":"ping"} → {"action":"pong"}
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from api.middleware.auth import require_auth, decode_token
from utils.db import acquire
from utils.redis_client import get_redis
from worker.notifier import REDIS_NOTIFY_CHANNEL

router = APIRouter(tags=["notifications"])
logger = logging.getLogger("ira.notifications")


# ── REST endpoints ────────────────────────────────────────────────────────────

@router.get("/notifications")
async def list_notifications(
    limit: int = Query(50, le=200),
    unread_only: bool = Query(False),
    _user: str = Depends(require_auth),
):
    where = "WHERE read=FALSE" if unread_only else ""
    async with acquire() as conn:
        rows = await conn.fetch(
            f"""SELECT id, category, title, body, priority, channels_sent, read, created_at
                FROM notifications {where}
                ORDER BY created_at DESC LIMIT $1""",
            limit,
        )
    return [
        {
            "id": str(r["id"]),
            "category": r["category"],
            "title": r["title"],
            "body": r["body"],
            "priority": r["priority"],
            "channels_sent": r["channels_sent"],
            "read": r["read"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


@router.post("/notifications/{notif_id}/read")
async def mark_read(notif_id: str, _user: str = Depends(require_auth)):
    async with acquire() as conn:
        await conn.execute(
            "UPDATE notifications SET read=TRUE WHERE id=$1",
            uuid.UUID(notif_id),
        )
    return {"status": "ok"}


@router.delete("/notifications/read")
async def clear_read(_user: str = Depends(require_auth)):
    async with acquire() as conn:
        rows = await conn.fetch(
            "DELETE FROM notifications WHERE read=TRUE RETURNING id"
        )
    return {"deleted": len(rows)}


# ── WebSocket real-time stream ────────────────────────────────────────────────

@router.websocket("/ws/notifications")
async def ws_notifications(
    websocket: WebSocket,
):
    """
    Real-time notification stream via WebSocket.
    Subscribes to Redis pub/sub and forwards all IRA notifications to the client.

    Authentication: send the JWT via the Sec-WebSocket-Protocol header using the
    format "bearer.<token>" — this keeps the token out of nginx access logs.
    Fallback: token query param is accepted for backwards compatibility in dev mode.
    """
    # Prefer token from Sec-WebSocket-Protocol header (avoids nginx log exposure)
    token: str | None = None
    protocol_header = websocket.headers.get("sec-websocket-protocol", "")
    for part in protocol_header.split(","):
        part = part.strip()
        if part.startswith("bearer."):
            token = part[len("bearer."):]
            break

    # Fallback: query param (dev / legacy clients)
    if not token:
        token = websocket.query_params.get("token")

    if not token:
        await websocket.close(code=4001)
        return

    try:
        decode_token(token)
    except Exception:
        await websocket.close(code=4001)
        return

    await websocket.accept()
    logger.info("WebSocket client connected for real-time notifications")

    redis = get_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe(REDIS_NOTIFY_CHANNEL)

    async def _send_loop():
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    await websocket.send_text(message["data"])
                except Exception:
                    break

    async def _receive_loop():
        """Handle ping/pong keepalive from client."""
        try:
            while True:
                data = await websocket.receive_text()
                try:
                    msg = json.loads(data)
                    if msg.get("action") == "ping":
                        await websocket.send_text('{"action":"pong"}')
                except Exception:
                    pass
        except WebSocketDisconnect:
            pass

    try:
        await asyncio.gather(_send_loop(), _receive_loop())
    except Exception as e:
        logger.warning(f"WebSocket session ended: {e}")
    finally:
        await pubsub.unsubscribe(REDIS_NOTIFY_CHANNEL)
        await pubsub.aclose()
        logger.info("WebSocket client disconnected")
