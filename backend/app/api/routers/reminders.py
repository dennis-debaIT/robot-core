from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

from app.database.db import get_connection

router = APIRouter()


@router.post("/reminders")
def create_reminder(payload: dict[str, Any]) -> dict[str, Any]:
    text = str(payload.get("text") or "").strip()
    fire_at = str(payload.get("fire_at") or "").strip()
    person_name = str(payload.get("person_name") or "").strip() or None
    if not text or not fire_at:
        return {"ok": False, "error": "text und fire_at erforderlich"}
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO reminders(text, fire_at, person_name, notified, dismissed, created_at) VALUES (?,?,?,0,0,?)",
            (text, fire_at, person_name, now),
        )
    return {"ok": True, "id": cur.lastrowid, "text": text, "fire_at": fire_at}


@router.get("/reminders/pending")
def get_pending_reminders() -> dict[str, Any]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, text, fire_at, person_name FROM reminders WHERE notified=1 AND dismissed=0 ORDER BY fire_at ASC"
        ).fetchall()
    return {"reminders": [dict(r) for r in rows]}


@router.post("/reminders/{reminder_id}/dismiss")
def dismiss_reminder(reminder_id: int) -> dict[str, Any]:
    with get_connection() as conn:
        conn.execute("UPDATE reminders SET dismissed=1 WHERE id=?", (reminder_id,))
    return {"ok": True}


@router.get("/reminders/active")
def get_active_reminders() -> dict[str, Any]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, text, fire_at, person_name, notified, light_command FROM reminders WHERE dismissed=0 ORDER BY fire_at ASC"
        ).fetchall()
    return {"reminders": [dict(r) for r in rows]}
