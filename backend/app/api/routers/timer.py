from __future__ import annotations

import time as _time
from typing import Any

from fastapi import APIRouter

from app.database.db import get_connection, read_state, write_state

router = APIRouter()

_TIMER_KEY = "active_timer"


def _now() -> float:
    return _time.time()


@router.post("/timer/set")
def set_timer(payload: dict[str, Any]) -> dict[str, Any]:
    duration = int(payload.get("duration_seconds", 0))
    if duration <= 0 or duration > 86400:
        return {"ok": False, "error": "Ungültige Dauer"}
    timer = {
        "started_at": _now(),
        "duration_seconds": duration,
        "finished": False,
        "label": str(payload.get("label", "")).strip() or None,
    }
    with get_connection() as conn:
        write_state(conn, _TIMER_KEY, timer)
    return {"ok": True, "duration_seconds": duration}


@router.get("/timer/status")
def get_timer_status() -> dict[str, Any]:
    with get_connection() as conn:
        timer = read_state(conn, _TIMER_KEY)
    if not timer:
        return {"active": False}
    elapsed = _now() - float(timer["started_at"])
    remaining = max(0.0, float(timer["duration_seconds"]) - elapsed)
    finished = remaining == 0.0
    if finished and not timer.get("finished"):
        timer["finished"] = True
        with get_connection() as conn:
            write_state(conn, _TIMER_KEY, timer)
    return {
        "active": True,
        "finished": finished,
        "remaining_seconds": round(remaining),
        "duration_seconds": int(timer["duration_seconds"]),
        "label": timer.get("label"),
        "elapsed_seconds": round(elapsed),
    }


@router.post("/timer/cancel")
def cancel_timer() -> dict[str, Any]:
    with get_connection() as conn:
        write_state(conn, _TIMER_KEY, None)
    return {"ok": True}


@router.post("/timer/dismiss")
def dismiss_timer() -> dict[str, Any]:
    """Abgelaufenen Timer quittieren (ausblenden ohne neuen zu starten)."""
    with get_connection() as conn:
        write_state(conn, _TIMER_KEY, None)
    return {"ok": True}
