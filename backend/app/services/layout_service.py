from __future__ import annotations

from app.database.db import get_connection, read_state, write_state

_STATE_KEY = "display_layout"

DEFAULT_LAYOUT: dict[str, str] = {
    "left_widget": "weather",    # "weather" | "calendar"
    "calendar_mode": "panel",    # "panel" | "nav_only"
}

_VALID = {
    "left_widget": {"weather", "calendar"},
    "calendar_mode": {"panel", "nav_only"},
}


class LayoutService:
    def get_layout(self) -> dict[str, str]:
        with get_connection() as conn:
            saved = read_state(conn, _STATE_KEY)
        merged = dict(DEFAULT_LAYOUT)
        if saved and isinstance(saved, dict):
            for k, allowed in _VALID.items():
                if saved.get(k) in allowed:
                    merged[k] = saved[k]
        return merged

    def save_layout(self, payload: dict) -> dict[str, str]:
        result = dict(DEFAULT_LAYOUT)
        for k, allowed in _VALID.items():
            if payload.get(k) in allowed:
                result[k] = payload[k]
        with get_connection() as conn:
            write_state(conn, _STATE_KEY, result)
        return result

    def reset_layout(self) -> dict[str, str]:
        with get_connection() as conn:
            write_state(conn, _STATE_KEY, DEFAULT_LAYOUT)
        return dict(DEFAULT_LAYOUT)
