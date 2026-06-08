from __future__ import annotations

from app.database.db import get_connection, read_state, write_state

_STATE_KEY = "display_theme"

DEFAULT_THEME: dict[str, str] = {
    "bg":       "#07070f",
    "surface":  "#0f0f1a",
    "surface2": "#16162a",
    "border":   "#1e1e38",
    "accent":   "#00c8ff",
    "accent2":  "#0077ff",
    "success":  "#00e676",
    "warning":  "#ffab00",
    "danger":   "#ff3d3d",
    "text":     "#e8eaf0",
    "muted":    "#6670aa",
    "face_bg":  "#04040c",
}


class ThemeService:
    def get_theme(self) -> dict[str, str]:
        with get_connection() as conn:
            saved = read_state(conn, _STATE_KEY)
        merged = dict(DEFAULT_THEME)
        if saved and isinstance(saved, dict):
            merged.update({k: v for k, v in saved.items() if k in DEFAULT_THEME})
        return merged

    def save_theme(self, payload: dict) -> dict[str, str]:
        cleaned: dict[str, str] = {}
        for key, default in DEFAULT_THEME.items():
            val = payload.get(key, default)
            if isinstance(val, str) and val.startswith("#") and len(val) in (4, 7, 9):
                cleaned[key] = val.lower()
            else:
                cleaned[key] = default
        with get_connection() as conn:
            write_state(conn, _STATE_KEY, cleaned)
        return cleaned

    def reset_theme(self) -> dict[str, str]:
        with get_connection() as conn:
            write_state(conn, _STATE_KEY, DEFAULT_THEME)
        return dict(DEFAULT_THEME)
