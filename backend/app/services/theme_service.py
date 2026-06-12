from __future__ import annotations

import os
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.database.db import get_connection, read_state, write_state

try:
    _LOCAL_TZ = ZoneInfo(os.environ.get("TZ", "Europe/Berlin"))
except ZoneInfoNotFoundError:
    _LOCAL_TZ = ZoneInfo("UTC")

_STATE_KEY = "display_theme"
_SCHEDULE_KEY = "display_theme_schedule"

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

# Gedämpftes Standard-Theme für die Nachtstunden (Zeitabhängiges Design, Plus).
DEFAULT_NIGHT_THEME: dict[str, str] = {
    "bg":       "#02020a",
    "surface":  "#080812",
    "surface2": "#0c0c18",
    "border":   "#16182c",
    "accent":   "#5a6acf",
    "accent2":  "#3a4aa0",
    "success":  "#00b85a",
    "warning":  "#cc8400",
    "danger":   "#cc3030",
    "text":     "#aab0d0",
    "muted":    "#454f7a",
    "face_bg":  "#000004",
}

DEFAULT_SCHEDULE: dict = {
    "enabled": False,
    "day_start": "07:00",
    "night_start": "21:00",
    "night_theme": dict(DEFAULT_NIGHT_THEME),
}


def _parse_hhmm(val: object, fallback: tuple[int, int]) -> dt_time:
    try:
        h, m = str(val).split(":")
        return dt_time(int(h) % 24, int(m) % 60)
    except Exception:
        return dt_time(*fallback)


def _fmt_hhmm(val: object, fallback: tuple[int, int]) -> str:
    t = _parse_hhmm(val, fallback)
    return f"{t.hour:02d}:{t.minute:02d}"


def _clean_theme_colors(payload: object, defaults: dict[str, str]) -> dict[str, str]:
    cleaned = dict(defaults)
    if isinstance(payload, dict):
        for key, default in defaults.items():
            val = payload.get(key, default)
            if isinstance(val, str) and val.startswith("#") and len(val) in (4, 7, 9):
                cleaned[key] = val.lower()
    return cleaned


class ThemeService:
    def get_theme(self) -> dict[str, str]:
        with get_connection() as conn:
            saved = read_state(conn, _STATE_KEY)
        merged = dict(DEFAULT_THEME)
        if saved and isinstance(saved, dict):
            merged.update({k: v for k, v in saved.items() if k in DEFAULT_THEME})
        return merged

    def save_theme(self, payload: dict) -> dict[str, str]:
        cleaned = _clean_theme_colors(payload, DEFAULT_THEME)
        with get_connection() as conn:
            write_state(conn, _STATE_KEY, cleaned)
        return cleaned

    def reset_theme(self) -> dict[str, str]:
        with get_connection() as conn:
            write_state(conn, _STATE_KEY, DEFAULT_THEME)
        return dict(DEFAULT_THEME)

    # ── Zeitabhängiges Design (Plus) ──────────────────────────

    def get_schedule(self) -> dict:
        with get_connection() as conn:
            saved = read_state(conn, _SCHEDULE_KEY)
        merged: dict = {
            "enabled": False,
            "day_start": DEFAULT_SCHEDULE["day_start"],
            "night_start": DEFAULT_SCHEDULE["night_start"],
            "night_theme": dict(DEFAULT_NIGHT_THEME),
        }
        if saved and isinstance(saved, dict):
            merged["enabled"] = bool(saved.get("enabled", False))
            merged["day_start"] = _fmt_hhmm(saved.get("day_start"), (7, 0))
            merged["night_start"] = _fmt_hhmm(saved.get("night_start"), (21, 0))
            merged["night_theme"] = _clean_theme_colors(saved.get("night_theme"), DEFAULT_NIGHT_THEME)
        return merged

    def save_schedule(self, payload: dict) -> dict:
        cleaned = {
            "enabled": bool(payload.get("enabled", False)),
            "day_start": _fmt_hhmm(payload.get("day_start"), (7, 0)),
            "night_start": _fmt_hhmm(payload.get("night_start"), (21, 0)),
            "night_theme": _clean_theme_colors(payload.get("night_theme"), DEFAULT_NIGHT_THEME),
        }
        with get_connection() as conn:
            write_state(conn, _SCHEDULE_KEY, cleaned)
        return cleaned

    def get_effective_theme(self) -> dict[str, str]:
        """Liefert das aktuell anzuzeigende Theme.

        Berücksichtigt das Zeitabhängige Design (Plus): ist es aktiviert und
        liegt die lokale Uhrzeit in der Nachtspanne, wird das Nacht-Theme
        zurückgegeben — sonst das normale (manuell konfigurierte) Theme.
        Ohne Plus-Lizenz bleibt das manuelle Theme immer aktiv, unabhängig
        vom gespeicherten Schedule-Zustand.
        """
        day_theme = self.get_theme()

        from app.services.feature_service import FeatureService
        if not FeatureService().has_feature("theme_schedule"):
            return day_theme

        schedule = self.get_schedule()
        if not schedule.get("enabled"):
            return day_theme

        if self._is_night(schedule):
            return dict(schedule["night_theme"])
        return day_theme

    @staticmethod
    def _is_night(schedule: dict) -> bool:
        now = datetime.now(_LOCAL_TZ).time()
        now_m = now.hour * 60 + now.minute
        day = _parse_hhmm(schedule.get("day_start"), (7, 0))
        night = _parse_hhmm(schedule.get("night_start"), (21, 0))
        day_m = day.hour * 60 + day.minute
        night_m = night.hour * 60 + night.minute
        if day_m == night_m:
            return False
        if day_m < night_m:
            # Normalfall: Tag-Fenster [day_m, night_m), Nacht außerhalb (über Mitternacht)
            return not (day_m <= now_m < night_m)
        # Vertauschte Zeiten: Nacht-Fenster [night_m, day_m)
        return night_m <= now_m < day_m
