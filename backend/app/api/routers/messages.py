"""Nachrichten-Proxy: Display ↔ Sync-Server."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services import sync_service as _sync
from app.services.integration_config_service import IntegrationConfigService

router = APIRouter(prefix="/messages", tags=["messages"])


def _display_name() -> str:
    cfg = IntegrationConfigService().get_config()
    return (cfg.get("system") or {}).get("device", {}).get("name") or "Erika"


def _normalize_messages(msgs: list) -> list:
    """Sync-Server gibt read_at zurück; Display/App erwarten read: bool."""
    for m in msgs:
        if "read" not in m:
            m["read"] = bool(m.get("read_at"))
    return msgs


@router.get("/inbox")
def get_inbox(since: str | None = None, limit: int = 50) -> dict[str, Any]:
    path = f"/messages/inbox?limit={min(limit, 200)}"
    if since:
        path += f"&since={since}"
    result = _sync._sync_request("GET", path)
    if result is None:
        return {"messages": [], "self_label": _display_name()}
    result["self_label"] = _display_name()
    _normalize_messages(result.get("messages", []))
    return result


class SendRequest(BaseModel):
    content: str
    recipient_type: str = "broadcast"
    recipient_id: str | None = None
    recipient_household_id: str | None = None
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
    if body.recipient_household_id:
        payload["recipient_household_id"] = body.recipient_household_id
    result = _sync._sync_request("POST", "/messages", payload)
    if result is None:
        raise HTTPException(status_code=503, detail="Sync-Server nicht erreichbar")
    # Push-Benachrichtigung übernimmt der Sync Server (er kennt sowohl lokale
    # als auch Haushalt-übergreifende Empfänger-Tokens); ein zusätzlicher Push
    # von hier würde lokale Nachrichten doppelt zustellen und würde bei
    # Haushalt-übergreifenden Nachrichten den Absender statt den Empfänger pushen.
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
        # Initial snapshot (messages returned DESC — msgs[0] is newest)
        result = await asyncio.to_thread(_sync._sync_request, "GET", "/messages/inbox?limit=50")
        msgs = (result or {}).get("messages", [])
        _normalize_messages(msgs)
        last_ts = msgs[0]["created_at"] if msgs else None
        yield f"data: {json.dumps({'messages': msgs, 'self_label': self_label})}\n\n"

        while not await request.is_disconnected():
            await asyncio.sleep(1.0)
            path = f"/messages/inbox?since={last_ts}&limit=20" if last_ts else "/messages/inbox?limit=20"
            result = await asyncio.to_thread(_sync._sync_request, "GET", path)
            new_msgs = (result or {}).get("messages", [])
            if new_msgs:
                _normalize_messages(new_msgs)
                # Antwort ist DESC sortiert — Cursor auf das späteste created_at
                # ODER read_at über den ganzen Batch vorrücken (Lesebestätigungen
                # können auf ältere Nachrichten mit neuerem read_at zeigen).
                for m in new_msgs:
                    last_ts = max(last_ts or "", m["created_at"], m.get("read_at") or "")
                yield f"data: {json.dumps({'messages': new_msgs, 'self_label': self_label})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
