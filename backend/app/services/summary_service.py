from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from app.database.db import get_connection, read_state, write_state

_DEFAULT_MODULES = [
    {"type": "calendar",   "enabled": True,  "exclude_calendars": []},
    {"type": "reminders",  "enabled": True},
    {"type": "weather",    "enabled": True},
    {"type": "pv",         "enabled": True},
    {"type": "vehicles",   "enabled": True,  "vehicle_ids": []},
    {"type": "robots",     "enabled": True},
    {"type": "notifications", "enabled": True},
]

_DEFAULT_TRIGGERS = ["guten morgen", "tageszusammenfassung", "was steht heute an"]


def _state_key(person_id: int) -> str:
    return f"summary_config_{person_id}"


def get_config(person_id: int) -> dict[str, Any]:
    with get_connection() as conn:
        cfg = read_state(conn, _state_key(person_id))
    if not isinstance(cfg, dict):
        return {"trigger_phrases": _DEFAULT_TRIGGERS, "modules": _DEFAULT_MODULES}
    cfg.setdefault("trigger_phrases", _DEFAULT_TRIGGERS)
    cfg.setdefault("modules", _DEFAULT_MODULES)
    return cfg


def save_config(person_id: int, config: dict[str, Any]) -> None:
    with get_connection() as conn:
        write_state(conn, _state_key(person_id), config)


def build_summary(person_id: int, person_name: str) -> str:
    from app.services.integration_config_service import IntegrationConfigService
    from app.search.providers.homeassistant import HomeAssistantProvider
    cfg = get_config(person_id)
    modules = cfg.get("modules") or _DEFAULT_MODULES
    ha = HomeAssistantProvider()
    int_cfg = IntegrationConfigService().get_config()
    parts: list[str] = []

    try:
        import os
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(os.environ.get("TZ", "Europe/Berlin"))
    except Exception:
        tz = timezone.utc

    now = datetime.now(tz)
    weekdays = ["Montag","Dienstag","Mittwoch","Donnerstag","Freitag","Samstag","Sonntag"]
    months = ["Januar","Februar","März","April","Mai","Juni","Juli","August","September","Oktober","November","Dezember"]
    date_str = f"{weekdays[now.weekday()]}, der {now.day}. {months[now.month-1]}"
    parts.append(f"Guten Morgen {person_name}. Heute ist {date_str}.")

    for mod in modules:
        if not mod.get("enabled"):
            continue
        mtype = mod.get("type")
        try:
            segment = _build_module(mtype, mod, ha, int_cfg, person_name, now, tz)
            if segment:
                parts.append(segment)
        except Exception:
            pass

    return " ".join(parts)


def _build_module(
    mtype: str,
    mod: dict,
    ha: Any,
    int_cfg: dict,
    person_name: str,
    now: datetime,
    tz: Any,
) -> str | None:

    if mtype == "calendar":
        return _module_calendar(mod, ha, int_cfg, now, tz)

    if mtype == "reminders":
        return _module_reminders(now, tz)

    if mtype == "weather":
        return _module_weather(int_cfg)

    if mtype == "pv":
        return _module_pv(int_cfg, ha)

    if mtype == "vehicles":
        return _module_vehicles(mod, int_cfg)

    if mtype == "robots":
        return _module_robots(int_cfg, ha)

    if mtype == "notifications":
        return _module_notifications()

    return None


def _module_calendar(mod: dict, ha: Any, int_cfg: dict, now: datetime, tz: Any) -> str | None:
    cal_cfg = int_cfg.get("calendar") or {}
    selected = cal_cfg.get("selected_calendars") or []
    exclude = [str(e).strip() for e in (mod.get("exclude_calendars") or [])]
    calendars = [c for c in selected if c not in exclude] if selected else []

    start_utc = now.replace(hour=0, minute=0, second=0).astimezone(timezone.utc)
    end_utc   = now.replace(hour=23, minute=59, second=59).astimezone(timezone.utc)
    fmt = "%Y-%m-%dT%H:%M:%S%z"

    events: list[dict] = []
    for cal_id in calendars:
        try:
            result = ha._get(f"/calendars/{cal_id}?start={start_utc.strftime(fmt)}&end={end_utc.strftime(fmt)}")
            if isinstance(result, list):
                events.extend(result)
        except Exception:
            pass

    if not events:
        # Keine Kalender konfiguriert → HA-Kalender direkt versuchen
        try:
            states = ha._get("/states")
            cal_entities = [s["entity_id"] for s in (states or []) if s.get("entity_id","").startswith("calendar.") and s["entity_id"] not in exclude]
            for cal_id in cal_entities[:5]:
                result = ha._get(f"/calendars/{cal_id}?start={start_utc.strftime(fmt)}&end={end_utc.strftime(fmt)}")
                if isinstance(result, list):
                    events.extend(result)
        except Exception:
            pass

    today_events = []
    for ev in events:
        summary = ev.get("summary") or ""
        start = ev.get("start") or {}
        time_str = start.get("dateTime") or start.get("date") or ""
        if time_str:
            try:
                dt = datetime.fromisoformat(time_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=tz)
                time_label = dt.astimezone(tz).strftime("%H:%M") if "T" in time_str else ""
                today_events.append((time_label, summary))
            except Exception:
                today_events.append(("", summary))

    if not today_events:
        return "Heute hast du keine Termine."
    count = len(today_events)
    items = ", ".join(f"{t} Uhr {s}" if t else s for t, s in today_events[:4])
    return f"Heute {'hast du' if count == 1 else 'hast du ' + str(count)} {'Termin' if count == 1 else 'Termine'}: {items}."


def _module_reminders(now: datetime, tz: Any) -> str | None:
    end_of_day = now.replace(hour=23, minute=59, second=59).astimezone(timezone.utc)
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT text, fire_at FROM reminders WHERE dismissed=0 AND fire_at <= ? ORDER BY fire_at ASC",
            (end_of_day.isoformat(),),
        ).fetchall()
    if not rows:
        return None
    count = len(rows)
    if count == 1:
        return f"Du hast eine Erinnerung: {rows[0]['text']}."
    items = ", ".join(r["text"] for r in rows[:3])
    return f"Du hast {count} Erinnerungen: {items}."


def _module_weather(int_cfg: dict) -> str | None:
    try:
        from app.search.providers.weather import WeatherProvider
        wp = WeatherProvider()
        data = wp.get_current()
        if not data:
            return None
        temp = data.get("temperature")
        desc = data.get("description") or data.get("condition") or ""
        if temp is not None:
            return f"Das Wetter: {desc}, {round(temp)} Grad."
        return f"Das Wetter: {desc}." if desc else None
    except Exception:
        return None


def _module_pv(int_cfg: dict, ha: Any) -> str | None:
    sensors = (int_cfg.get("pv") or {}).get("sensors") or {}
    if not (int_cfg.get("pv") or {}).get("enabled"):
        return None
    power_id = sensors.get("power")
    daily_id = sensors.get("daily")
    if not power_id:
        return None
    try:
        power_state = ha.get_state(power_id)
        power = float((power_state or {}).get("state", "0") or 0)
        unit = ((power_state or {}).get("attributes") or {}).get("unit_of_measurement", "W")
        text = f"Die PV-Anlage liefert aktuell {round(power)} {unit}."
        if daily_id:
            daily_state = ha.get_state(daily_id)
            daily = float((daily_state or {}).get("state", "0") or 0)
            daily_unit = ((daily_state or {}).get("attributes") or {}).get("unit_of_measurement", "kWh")
            text += f" Heute wurden {daily} {daily_unit} erzeugt."
        return text
    except Exception:
        return None


def _module_vehicles(mod: dict, int_cfg: dict) -> str | None:
    from app.services.vehicle_service import VehicleService
    svc = VehicleService()
    data = svc.list_vehicles(int_cfg)
    vehicles = data.get("vehicles") or []
    selected_ids = [str(v) for v in (mod.get("vehicle_ids") or [])]
    if selected_ids:
        vehicles = [v for v in vehicles if v.get("id") in selected_ids]
    if not vehicles:
        return None
    parts = []
    for v in vehicles:
        label = v.get("label") or v.get("id")
        # E-Auto: Akku + Reichweite
        battery = v.get("battery")
        if battery:
            pct = battery.get("state")
            rng = v.get("range")
            rng_text = f", Reichweite {rng['state']} {rng.get('unit','km')}" if rng else ""
            parts.append(f"{label}: {pct}%{rng_text}.")
            continue
        # Verbrenner: Tank + Reichweite
        fuel = v.get("fuel_level")
        if fuel:
            pct = fuel.get("state")
            unit = fuel.get("unit") or "%"
            rng = v.get("range")
            rng_text = f", Reichweite {rng['state']} {rng.get('unit','km')}" if rng else ""
            parts.append(f"{label}: {pct} {unit} Tank{rng_text}.")
    return " ".join(parts) if parts else None


# Vollständige Übersetzungstabelle für Roboter-States
_ROBOT_STATE_DE: dict[str, str] = {
    # Saugroboter (iRobot, Roborock, Ecovacs, Dreame, Viomi …)
    "docked":              "steht in der Basis",
    "charging":            "lädt",
    "cleaning":            "saugt gerade",
    "returning":           "fährt zur Basis",
    "returning_to_dock":   "fährt zur Basis",
    "idle":                "ist bereit",
    "paused":              "ist pausiert",
    "error":               "hat einen Fehler",
    "unavailable":         "nicht erreichbar",
    "unknown":             "Status unbekannt",
    "manual":              "manuelle Steuerung",
    "mapping":             "erstellt Karte",
    "spot":                "reinigt einen Bereich",
    "auto":                "saugt automatisch",
    "edge":                "reinigt Kanten",
    "moving":              "ist unterwegs",
    # Dreame / Roborock erweitert
    "washing":             "reinigt Wischpad",
    "drying":              "trocknet Wischpad",
    "self_cleaning":       "reinigt sich selbst",
    "self_drying":         "trocknet Wischpad",
    "charging_completed":  "ist voll geladen",
    "charge":              "lädt",
    "sleep":               "schläft",
    "standby":             "wartet",
    "full_charge":         "ist voll geladen",
    "sweeping":            "saugt gerade",
    "sweeping_and_mopping":"saugt und wischt",
    "mopping":             "wischt gerade",
    "cruising":            "patrouilliert",
    # Mähroboter (Husqvarna Automower, Worx Landroid …)
    "mowing":              "mäht gerade",
    "going_home":          "fährt zur Basis",
    "parked":              "parkt",
    "stopped":             "ist gestoppt",
    "cutting":             "mäht gerade",
    "leaving":             "verlässt Basis",
    "searching_zone":      "sucht Mähzone",
    "zone_out":            "mäht außerhalb Zone",
    "week_timer":          "Wochenplan aktiv",
    "completed":           "ist fertig",
    "not_applicable":      "nicht verfügbar",
    "connection_issue":    "Verbindungsproblem",
}


def _translate_robot_state(state: str, custom_mappings: dict | None = None) -> str:
    s = state.strip().lower()
    # 1. Custom-Mapping aus HA-Konfiguration (höchste Priorität)
    if custom_mappings:
        for k, v in custom_mappings.items():
            if k.lower() == s:
                return v
    # 2. Eingebaute Tabelle
    if s in _ROBOT_STATE_DE:
        return _ROBOT_STATE_DE[s]
    # 3. Rohtext als Fallback (lesbarer machen)
    return state.replace("_", " ")


def _module_robots(int_cfg: dict, ha: Any) -> str | None:
    from app.services.robot_service import RobotService
    try:
        svc = RobotService()
        robots = svc.list_robots()
        if not robots:
            return None
        # Custom state_mappings aus Konfiguration laden
        robots_cfg = int_cfg.get("robots") or {}
        state_mappings = robots_cfg.get("state_mappings") or {}

        parts = []
        for r in robots[:5]:
            name = r.get("name") or r.get("entity_id", "Roboter")
            state = r.get("state") or ""
            if state.lower() in ("unavailable", "unknown", ""):
                continue
            label = _translate_robot_state(state, state_mappings)
            parts.append(f"{name} {label}.")
        return " ".join(parts) if parts else None
    except Exception:
        return None


def _module_notifications() -> str | None:
    with get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) AS n FROM notifications WHERE read=0").fetchone()["n"]
    if count == 0:
        return None
    return f"Du hast {count} ungelesene {'Benachrichtigung' if count == 1 else 'Benachrichtigungen'}."
