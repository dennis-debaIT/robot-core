"""Nachrichten-Proxy: Display ↔ Sync-Server."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import sync_service as _sync
from app.services.integration_config_service import IntegrationConfigService

router = APIRouter(prefix="/messages", tags=["messages"])


def _display_name() -> str:
    cfg = IntegrationConfigService().get_config()
    return (cfg.get("messages") or {}).get("display_name") or "Erika"


@router.get("/inbox")
def get_inbox(since: str | None = None, limit: int = 50) -> dict[str, Any]:
    path = f"/messages/inbox?limit={min(limit, 200)}"
    if since:
        path += f"&since={since}"
    result = _sync._sync_request("GET", path)
    if result is None:
        return {"messages": []}
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
    return result


@router.patch("/{message_id}/read")
def mark_read(message_id: str) -> dict[str, Any]:
    result = _sync._sync_request("PATCH", f"/messages/{message_id}/read")
    if result is None:
        raise HTTPException(status_code=503, detail="Sync-Server nicht erreichbar")
    return result
