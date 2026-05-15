from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.deps import get_core
from app.api.schemas import ChatRequest


router = APIRouter()


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
