from __future__ import annotations

import time as _time
from typing import Any

from fastapi import APIRouter

from app.database.db import get_connection, read_state, write_state

router = APIRouter()

_TIMER_KEY = "active_timers"


def _now() -> float:
    return _time.time()


def _get_timers(conn) -> list[dict]:
    data = read_state(conn, _TIMER_KEY)
    if isinstance(data, list):
        return data
    # Migrate old single-timer format
    if isinstance(data, dict) and "started_at" in data:
        return [{**data, "id": 1, "label": data.get("label") or "Timer 1"}]
    return []


def _save_timers(conn, timers: list[dict]) -> None:
    write_state(conn, _TIMER_KEY, timers or None)


def _enrich(t: dict) -> dict:
    elapsed = _now() - float(t["started_at"])
    remaining = max(0.0, float(t["duration_seconds"]) - elapsed)
    finished = remaining == 0.0
    return {
        "id": t["id"],
        "active": True,
        "finished": finished,
        "remaining_seconds": round(remaining),
        "duration_seconds": int(t["duration_seconds"]),
        "label": t.get("label"),
        "elapsed_seconds": round(elapsed),
    }


@router.post("/timer/set")
def set_timer(payload: dict[str, Any]) -> dict[str, Any]:
    duration = int(payload.get("duration_seconds", 0))
    if duration <= 0 or duration > 86400:
        return {"ok": False, "error": "Ungültige Dauer"}
    with get_connection() as conn:
        timers = _get_timers(conn)
        new_id = max((t["id"] for t in timers), default=0) + 1
        label = str(payload.get("label", "")).strip() or f"Timer {new_id}"
        timers.append({
            "id": new_id,
            "started_at": _now(),
            "duration_seconds": duration,
            "finished": False,
            "label": label,
        })
        _save_timers(conn, timers)
    return {"ok": True, "id": new_id, "duration_seconds": duration}


@router.get("/timer/status")
def get_timer_status() -> dict[str, Any]:
    with get_connection() as conn:
        timers = _get_timers(conn)
    if not timers:
        return {"active": False, "timers": []}
    now = _now()
    enriched = []
    newly_finished: list[dict] = []
    for t in timers:
        elapsed = now - float(t["started_at"])
        remaining = max(0.0, float(t["duration_seconds"]) - elapsed)
        finished = remaining == 0.0
        if finished and not t.get("finished"):
            t["finished"] = True
            newly_finished.append(t)
        enriched.append({
            "id": t["id"],
            "active": True,
            "finished": finished,
            "remaining_seconds": round(remaining),
            "duration_seconds": int(t["duration_seconds"]),
            "label": t.get("label"),
            "elapsed_seconds": round(elapsed),
        })
    if newly_finished:
        with get_connection() as conn:
            _save_timers(conn, timers)
    return {"active": True, "timers": enriched}


@router.post("/timer/cancel")
def cancel_timer() -> dict[str, Any]:
    with get_connection() as conn:
        _save_timers(conn, [])
    return {"ok": True}


@router.post("/timer/dismiss")
def dismiss_timer() -> dict[str, Any]:
    """Alle abgelaufenen Timer quittieren."""
    with get_connection() as conn:
        remaining = [t for t in _get_timers(conn) if not t.get("finished")]
        _save_timers(conn, remaining)
    return {"ok": True}


@router.post("/timer/{timer_id}/cancel")
def cancel_timer_by_id(timer_id: int) -> dict[str, Any]:
    with get_connection() as conn:
        timers = [t for t in _get_timers(conn) if t["id"] != timer_id]
        _save_timers(conn, timers)
    return {"ok": True}


@router.post("/timer/{timer_id}/dismiss")
def dismiss_timer_by_id(timer_id: int) -> dict[str, Any]:
    with get_connection() as conn:
        timers = [t for t in _get_timers(conn) if t["id"] != timer_id]
        _save_timers(conn, timers)
    return {"ok": True}
