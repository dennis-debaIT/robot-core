from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import get_core
from app.api.schemas import FactUpdateRequest, PersonPreferencePatchRequest


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
