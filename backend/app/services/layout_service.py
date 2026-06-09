from __future__ import annotations

from app.database.db import get_connection, read_state, write_state

_STATE_KEY = "display_layout"

_VALID_WIDGETS = {"weather", "calendar", "fuel", "pv", "ev", "cameras", "waste"}

DEFAULT_LAYOUT: dict = {
    "left": [
        {"widget": "weather",  "size": 2},
        {"widget": "fuel",     "size": 1},
        {"widget": "ev",       "size": 1},
    ],
    "right": [
        {"widget": "calendar", "size": 3},
        {"widget": "pv",       "size": 1},
    ],
}


def _sanitize_slots(slots: list) -> list:
    result = []
    for s in slots:
        if not isinstance(s, dict):
            continue
        widget = s.get("widget")
        if widget not in _VALID_WIDGETS:
            continue
        size = s.get("size", 1)
        try:
            size = max(1, min(8, int(size)))
        except (TypeError, ValueError):
            size = 1
        result.append({"widget": widget, "size": size})
    return result


def _no_duplicates(left: list, right: list) -> tuple[list, list]:
    seen: set[str] = set()
    clean_left = []
    for s in left:
        if s["widget"] not in seen:
            seen.add(s["widget"])
            clean_left.append(s)
    clean_right = []
    for s in right:
        if s["widget"] not in seen:
            seen.add(s["widget"])
            clean_right.append(s)
    return clean_left, clean_right


class LayoutService:
    def get_layout(self) -> dict:
        with get_connection() as conn:
            saved = read_state(conn, _STATE_KEY)
        if not saved or not isinstance(saved, dict):
            return DEFAULT_LAYOUT
        left  = _sanitize_slots(saved.get("left",  []))
        right = _sanitize_slots(saved.get("right", []))
        if not left and not right:
            return DEFAULT_LAYOUT
        left, right = _no_duplicates(left, right)
        return {"left": left, "right": right}

    def save_layout(self, payload: dict) -> dict:
        left  = _sanitize_slots(payload.get("left",  []))
        right = _sanitize_slots(payload.get("right", []))
        left, right = _no_duplicates(left, right)
        result = {"left": left, "right": right}
        with get_connection() as conn:
            write_state(conn, _STATE_KEY, result)
        return result

    def reset_layout(self) -> dict:
        with get_connection() as conn:
            write_state(conn, _STATE_KEY, DEFAULT_LAYOUT)
        return DEFAULT_LAYOUT
