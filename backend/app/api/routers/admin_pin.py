from __future__ import annotations

import hashlib
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.database.db import get_connection, read_state, write_state

router = APIRouter(prefix="/admin/pin", tags=["admin-pin"])

_STATE_KEY = "admin_pin_hash"


def _hash(pin: str) -> str:
    return hashlib.sha256(pin.strip().encode()).hexdigest()


def _get_stored_hash(conn) -> str | None:
    return read_state(conn, _STATE_KEY, None)


class PinBody(BaseModel):
    pin: str
    current_pin: str | None = None


@router.get("/status")
def pin_status() -> dict[str, Any]:
    with get_connection() as conn:
        return {"set": bool(_get_stored_hash(conn))}


def _audit(action: str, summary: str, level: str = "info") -> None:
    try:
        from app.audit.service import AuditService
        AuditService().log(action=action, target_type="admin", target_id="pin",
                           actor_type="local_admin", summary=summary, level=level)
    except Exception:
        pass


@router.post("/verify")
def verify_pin(body: PinBody) -> dict[str, Any]:
    with get_connection() as conn:
        stored = _get_stored_hash(conn)
    if not stored:
        return {"ok": True}  # kein PIN gesetzt → immer OK
    ok = _hash(body.pin) == stored
    if not ok:
        _audit("admin.pin.verify.fail", "Falsche PIN-Eingabe im Admin-Bereich", level="warning")
    return {"ok": ok}


@router.post("/set")
def set_pin(body: PinBody) -> dict[str, Any]:
    if not body.pin or len(body.pin.strip()) < 4:
        raise HTTPException(status_code=400, detail="PIN muss mindestens 4 Stellen haben")
    if not body.pin.strip().isdigit():
        raise HTTPException(status_code=400, detail="PIN darf nur Ziffern enthalten")

    with get_connection() as conn:
        stored = _get_stored_hash(conn)
        if stored:
            if not body.current_pin or _hash(body.current_pin) != stored:
                raise HTTPException(status_code=403, detail="Aktueller PIN falsch")
        write_state(conn, _STATE_KEY, _hash(body.pin))
    _audit("admin.pin.set", "Admin-PIN wurde gesetzt" if not stored else "Admin-PIN wurde geändert")
    return {"ok": True}


@router.delete("")
def remove_pin(body: PinBody) -> dict[str, Any]:
    with get_connection() as conn:
        stored = _get_stored_hash(conn)
        if stored and (_hash(body.pin) != stored):
            raise HTTPException(status_code=403, detail="PIN falsch")
        write_state(conn, _STATE_KEY, None)
    _audit("admin.pin.removed", "Admin-PIN wurde entfernt")
    return {"ok": True}
