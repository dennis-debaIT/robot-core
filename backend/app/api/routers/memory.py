from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import get_core
from app.api.schemas import FactUpdateRequest, MemoryProposalRequest


router = APIRouter()


@router.get("/memory")
def list_memory(
    status: str | None = Query(default=None),
    subject: str | None = Query(default=None),
) -> dict[str, Any]:
    return {"items": get_core().memory.list_memories(status=status, subject=subject)}


@router.post("/memory/propose")
def propose_memory(payload: MemoryProposalRequest) -> dict[str, Any]:
    memory = get_core().propose_memory(
        content=payload.content,
        category=payload.category,
        subject=payload.subject,
        source=payload.source,
    )
    return {"memory": memory}


@router.post("/memory/approve/{memory_id}")
def approve_memory(memory_id: int) -> dict[str, Any]:
    result = get_core().approve_memory(memory_id)
    if not result:
        raise HTTPException(status_code=404, detail="Memory not found")
    return result


@router.post("/memory/reject/{memory_id}")
def reject_memory(memory_id: int) -> dict[str, Any]:
    result = get_core().reject_memory(memory_id)
    if not result:
        raise HTTPException(status_code=404, detail="Memory not found")
    return result


@router.patch("/memory/{memory_id}")
def update_memory(memory_id: int, payload: FactUpdateRequest) -> dict[str, Any]:
    result = get_core().memory.update_content(memory_id, payload.value)
    if not result:
        raise HTTPException(status_code=404, detail="Memory not found")
    return result


@router.delete("/memory/{memory_id}")
def delete_memory(memory_id: int) -> dict[str, Any]:
    result = get_core().memory.delete(memory_id)
    if not result:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"ok": True}
