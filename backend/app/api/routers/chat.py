from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.deps import get_core
from app.api.schemas import ChatRequest
from app.database.db import get_connection


router = APIRouter()


class LogMessageRequest(BaseModel):
    role: str
    message: str
    person_name: str | None = None


@router.post("/chat/log")
def log_message(payload: LogMessageRequest) -> dict[str, object]:
    if payload.role not in ("assistant",):
        return {"ok": False, "error": "only assistant role allowed"}
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO conversation_messages(role, person_name, message, created_at) VALUES (?,?,?,?)",
            (payload.role, payload.person_name, payload.message, datetime.now(timezone.utc).isoformat()),
        )
    return {"ok": True}


@router.post("/chat")
def chat(payload: ChatRequest) -> dict[str, object]:
    return get_core().chat(payload.message, payload.person_name)


@router.post("/chat/preview")
def preview_chat(payload: ChatRequest) -> dict[str, object]:
    return get_core().preview_chat_prompt(payload.message, payload.person_name)


@router.post("/chat/stream")
def stream_chat(payload: ChatRequest) -> StreamingResponse:
    return StreamingResponse(
        get_core().stream_chat(payload.message, payload.person_name),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
