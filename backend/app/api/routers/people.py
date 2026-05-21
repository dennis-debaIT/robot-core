from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

import json
from datetime import datetime, timezone

from app.api.deps import get_core
from app.api.schemas import FactUpdateRequest, PersonPreferencePatchRequest
from app.database.db import get_connection, read_state, write_state


router = APIRouter()


@router.get("/audit")
def list_audit(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    return {"items": get_core().list_audit_entries(limit=limit)}


@router.get("/conversation")
def list_conversation(
    person_name: str | None = Query(default=None),
    limit: int = Query(default=40, ge=1, le=200),
) -> dict[str, Any]:
    return {"items": get_core().list_conversation_messages(person_name=person_name, limit=limit)}


@router.get("/profiles")
def list_profiles() -> dict[str, Any]:
    return {"items": get_core().list_profiles()}


@router.get("/profiles/{person_id}/workspace")
def get_profile_workspace(person_id: int) -> dict[str, Any]:
    result = get_core().get_person_workspace(person_id)
    if not result:
        raise HTTPException(status_code=404, detail="Person not found")
    return result


@router.get("/profiles/{person_id}/preferences")
def get_profile_preferences(person_id: int) -> dict[str, Any]:
    result = get_core().get_person_preferences(person_id)
    if not result:
        raise HTTPException(status_code=404, detail="Person not found")
    return result


@router.patch("/profiles/{person_id}/preferences")
def patch_profile_preferences(person_id: int, payload: PersonPreferencePatchRequest) -> dict[str, Any]:
    result = get_core().update_person_preferences(person_id, payload.to_patch())
    if not result:
        raise HTTPException(status_code=404, detail="Person not found")
    return result


@router.delete("/profiles/{person_id}")
def delete_profile(person_id: int) -> dict[str, Any]:
    result = get_core().delete_person(person_id)
    if not result:
        raise HTTPException(status_code=404, detail="Person not found")
    return result


@router.delete("/profiles/{person_id}/facts/{fact_id}")
def delete_profile_fact(person_id: int, fact_id: int) -> dict[str, Any]:
    result = get_core().profile.delete_fact(person_id, fact_id)
    if not result:
        raise HTTPException(status_code=404, detail="Person or fact not found")
    return result


@router.patch("/profiles/{person_id}/facts/{fact_id}")
def update_profile_fact(person_id: int, fact_id: int, payload: FactUpdateRequest) -> dict[str, Any]:
    result = get_core().profile.update_fact(person_id, fact_id, payload.value)
    if not result:
        raise HTTPException(status_code=404, detail="Person or fact not found")
    return result


@router.post("/profiles/{person_id}/persona/reset")
def reset_person_persona(person_id: int) -> dict[str, Any]:
    result = get_core().reset_person_persona(person_id)
    if not result:
        raise HTTPException(status_code=404, detail="Person not found")
    return result


@router.post("/profiles")
def create_profile(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    name = str(payload.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name darf nicht leer sein")
    person = get_core().profile.ensure_person_stub(name)
    return {"person": person}


@router.get("/active-person")
def get_active_person() -> dict[str, Any]:
    with get_connection() as conn:
        name = read_state(conn, "active_person_name")
    return {"name": name}


@router.post("/active-person")
def set_active_person(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    name = payload.get("name")
    if name is not None:
        name = str(name).strip() or None
    with get_connection() as conn:
        write_state(conn, "active_person_name", name)
    return {"name": name}


# ── Gesichtserkennung ─────────────────────────────────────────────────────────

@router.post("/profiles/{person_id}/face-descriptors")
def save_face_descriptors(person_id: int, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    descriptors = payload.get("descriptors")
    if not isinstance(descriptors, list) or not descriptors:
        raise HTTPException(status_code=400, detail="descriptors (Liste von Arrays) fehlen")
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute("DELETE FROM person_face_descriptors WHERE person_id = ?", (person_id,))
        for desc in descriptors:
            conn.execute(
                "INSERT INTO person_face_descriptors(person_id, descriptor, created_at) VALUES (?,?,?)",
                (person_id, json.dumps(desc), now),
            )
    return {"ok": True, "count": len(descriptors)}


@router.delete("/profiles/{person_id}/face-descriptors")
def delete_face_descriptors(person_id: int) -> dict[str, Any]:
    with get_connection() as conn:
        conn.execute("DELETE FROM person_face_descriptors WHERE person_id = ?", (person_id,))
    return {"ok": True}


@router.get("/profiles/face-descriptors/all")
def get_all_face_descriptors() -> dict[str, Any]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT p.id, p.name, pfd.descriptor
               FROM person_face_descriptors pfd
               JOIN persons p ON p.id = pfd.person_id
               ORDER BY p.name"""
        ).fetchall()
    persons: dict[str, list] = {}
    for row in rows:
        name = row["name"]
        persons.setdefault(name, []).append(json.loads(row["descriptor"]))
    return {"persons": [{"name": n, "descriptors": d} for n, d in persons.items()]}
