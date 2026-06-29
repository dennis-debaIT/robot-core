from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_state: dict[str, dict[str, float]] = {}


def mark_success(source: str) -> None:
    now = time.monotonic()
    with _lock:
        entry = _state.setdefault(source, {})
        entry["last_success"] = now
        entry["last_attempt"] = now


def mark_attempt(source: str) -> None:
    now = time.monotonic()
    with _lock:
        _state.setdefault(source, {})["last_attempt"] = now


def get_health() -> dict[str, int | None]:
    """Liefert pro Quelle die Anzahl Sekunden seit letztem Erfolg.
    None = kein Problem oder nicht aktiv abgefragt.
    int  = seit dieser Anzahl Sekunden kein Erfolg (obwohl kürzlich versucht).
    """
    now = time.monotonic()
    result: dict[str, int | None] = {}
    with _lock:
        for source, entry in _state.items():
            last_attempt = entry.get("last_attempt", 0.0)
            last_success = entry.get("last_success", 0.0)
            if now - last_attempt > 600:
                result[source] = None
                continue
            stale = int(now - last_success) if last_success else int(now - last_attempt)
            result[source] = stale if stale > 30 else None
    return result
