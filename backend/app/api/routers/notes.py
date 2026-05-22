from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

from app.services.note_service import NoteService

router = APIRouter()
_svc = NoteService()


@router.get("/notes")
def list_notes(person_id: int | None = Query(default=None)) -> dict[str, Any]:
    return {"items": _svc.list_notes(person_id=person_id)}


@router.get("/notes/global")
def list_global_notes() -> dict[str, Any]:
    return {"items": _svc.list_global()}


@router.get("/notes/search")
def search_notes(q: str = Query(...), person_id: int | None = Query(default=None)) -> dict[str, Any]:
    return {"items": _svc.search(q, person_id=person_id)}


@router.post("/notes")
def create_note(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    title   = str(payload.get("title") or "").strip()
    content = str(payload.get("content") or "").strip()
    person_id = payload.get("person_id")
    if not title or not content:
        raise HTTPException(status_code=400, detail="title und content erforderlich")
    return _svc.create(title=title, content=content, person_id=person_id)


@router.patch("/notes/{note_id}")
def update_note(note_id: int, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    result = _svc.update(
        note_id,
        title=payload.get("title"),
        content=payload.get("content"),
    )
    if not result:
        raise HTTPException(status_code=404, detail="Notiz nicht gefunden")
    return result


@router.delete("/notes/{note_id}")
def delete_note(note_id: int) -> dict[str, Any]:
    if not _svc.delete(note_id):
        raise HTTPException(status_code=404, detail="Notiz nicht gefunden")
    return {"ok": True}


@router.get("/profiles/{person_id}/notes")
def list_person_notes(person_id: int) -> dict[str, Any]:
    return {"items": _svc.list_for_person(person_id)}
