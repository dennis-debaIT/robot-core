"""Nachrichten-Proxy: Display ↔ Sync-Server."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services import sync_service as _sync
from app.services import push_service as _push
from app.services.integration_config_service import IntegrationConfigService

router = APIRouter(prefix="/messages", tags=["messages"])


def _display_name() -> str:
    cfg = IntegrationConfigService().get_config()
    return (cfg.get("system") or {}).get("device", {}).get("name") or "Erika"


@router.get("/inbox")
def get_inbox(since: str | None = None, limit: int = 50) -> dict[str, Any]:
    path = f"/messages/inbox?limit={min(limit, 200)}"
    if since:
        path += f"&since={since}"
    result = _sync._sync_request("GET", path)
    if result is None:
        return {"messages": [], "self_label": _display_name()}
    result["self_label"] = _display_name()
    return result


class SendRequest(BaseModel):
    content: str
    recipient_type: str = "broadcast"
    recipient_id: str | None = None
    message_type: str = "text"


@router.post("")
def send_message(body: SendRequest) -> dict[str, Any]:
    payload = {
        "content": body.content,
        "recipient_type": body.recipient_type,
        "message_type": body.message_type,
        "sender_label": _display_name(),
    }
    if body.recipient_id:
        payload["recipient_id"] = body.recipient_id
    result = _sync._sync_request("POST", "/messages", payload)
    if result is None:
        raise HTTPException(status_code=503, detail="Sync-Server nicht erreichbar")
    # Push notification to all registered app devices
    _push.send_notification(
        title=_display_name(),
        body=body.content[:200],
        channel="messages",
    )
    return result


@router.patch("/{message_id}/read")
def mark_read(message_id: str) -> dict[str, Any]:
    result = _sync._sync_request("PATCH", f"/messages/{message_id}/read")
    if result is None:
        raise HTTPException(status_code=503, detail="Sync-Server nicht erreichbar")
    return result


@router.get("/contacts")
def get_contacts() -> dict[str, Any]:
    result = _sync._sync_request("GET", "/messages/contacts")
    if result is None:
        return {"contacts": []}
    return result


@router.get("/stream")
async def stream_messages_display(request: Request) -> StreamingResponse:
    """SSE-Proxy für das Display: pollt Sync-Server sekündlich und streamt neue Nachrichten."""

    async def generate():
        self_label = _display_name()
        # Initial snapshot
        result = await asyncio.to_thread(_sync._sync_request, "GET", "/messages/inbox?limit=50")
        msgs = (result or {}).get("messages", [])
        last_ts = msgs[-1]["created_at"] if msgs else None
        yield f"data: {json.dumps({'messages': msgs, 'self_label': self_label})}\n\n"

        while not await request.is_disconnected():
            await asyncio.sleep(1.0)
            path = f"/messages/inbox?since={last_ts}&limit=20" if last_ts else "/messages/inbox?limit=20"
            result = await asyncio.to_thread(_sync._sync_request, "GET", path)
            new_msgs = (result or {}).get("messages", [])
            if new_msgs:
                last_ts = new_msgs[-1]["created_at"]
                yield f"data: {json.dumps({'messages': new_msgs, 'self_label': self_label})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
