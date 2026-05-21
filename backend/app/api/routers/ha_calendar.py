from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from app.services.calendar_write_service import CalendarWriteService

router = APIRouter()


@router.get("/ha/calendar/entities")
def list_calendar_entities() -> dict[str, Any]:
    return {"entities": CalendarWriteService.list_calendar_entities()}


@router.post("/ha/calendar/create")
def create_calendar_event(payload: dict[str, Any]) -> dict[str, Any]:
    entity_id  = str(payload.get("entity_id") or "").strip()
    summary    = str(payload.get("summary") or "").strip()
    start_iso  = str(payload.get("start_datetime") or "").strip()
    duration_m = int(payload.get("duration_min") or 60)
    description = str(payload.get("description") or "").strip()

    if not entity_id or not summary or not start_iso:
        raise HTTPException(status_code=400, detail="entity_id, summary und start_datetime sind Pflicht")

    try:
        start_dt = datetime.fromisoformat(start_iso)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Ungültiges Datum: {start_iso}") from exc

    end_dt = start_dt + timedelta(minutes=max(1, duration_m))
    svc = CalendarWriteService()
    ok = svc.create_event(entity_id, summary, start_dt, end_dt, description)
    if not ok:
        raise HTTPException(status_code=502, detail="HA-Kalender-Eintrag fehlgeschlagen")
    return {"ok": True, "summary": summary, "start": start_dt.isoformat(), "end": end_dt.isoformat()}
