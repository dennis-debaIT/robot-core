from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query

from app.search.providers.homeassistant import HomeAssistantProvider
from app.services.integration_config_service import IntegrationConfigService
from app.services.pv_service import PV_PROVIDERS, PvService

router = APIRouter()

_DE_WEEKDAYS_SHORT = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
_DE_MONTHS_SHORT   = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
                       "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]

try:
    _LOCAL_TZ = ZoneInfo(os.environ.get("TZ", "Europe/Berlin"))
except ZoneInfoNotFoundError:
    _LOCAL_TZ = ZoneInfo("UTC")


def _pv_sensors(config: dict) -> dict[str, str]:
    return (config.get("pv") or {}).get("sensors") or {}


def _safe_float(v: Any) -> float | None:
    try:
        f = float(v)
        return None if f != f else f  # NaN → None
    except (TypeError, ValueError):
        return None


def _to_local(raw: str) -> datetime | None:
    """Parst ISO-Zeitstempel und konvertiert in lokale Zeit via zoneinfo."""
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_LOCAL_TZ).replace(tzinfo=None)
    except Exception:
        return None


def _history_to_5min_max(states: list[dict]) -> tuple[list[str], list[float | None]]:
    """Aggregiert Rohzustände zu 5-Minuten-Maximalwerten (lokale Zeit)."""
    buckets: dict[str, list[float]] = defaultdict(list)
    for s in states:
        v = _safe_float(s.get("state"))
        if v is None or v <= 0:
            continue  # Null-Meldungen ignorieren
        dt = _to_local(s.get("last_changed") or s.get("last_updated") or "")
        if not dt:
            continue
        total_min = dt.hour * 60 + dt.minute
        bucket = (total_min // 5) * 5
        key = f"{bucket // 60:02d}:{bucket % 60:02d}"
        buckets[key].append(v)
    labels, values = [], []
    for key in sorted(buckets):
        labels.append(key)
        vals = buckets[key]
        values.append(round(max(vals), 1) if vals else None)
    return labels, values


def _history_to_daily_max(states: list[dict]) -> dict[str, float]:
    """Liefert {date_str: max_value} aus Rohzuständen (lokale Zeit)."""
    daily: dict[str, float] = {}
    for s in states:
        v = _safe_float(s.get("state"))
        if v is None:
            continue
        dt = _to_local(s.get("last_changed") or s.get("last_updated") or "")
        if not dt:
            continue
        date_key = dt.strftime("%Y-%m-%d")
        daily[date_key] = max(daily.get(date_key, 0.0), v)
    return daily


@router.get("/ha/pv/providers")
def get_pv_providers() -> dict[str, Any]:
    return {
        "providers": [
            {"id": k, "label": v["label"], "sensors": v["sensors"]}
            for k, v in PV_PROVIDERS.items()
        ]
    }


@router.get("/ha/pv/state")
def get_pv_state() -> dict[str, Any]:
    config = IntegrationConfigService().get_config()
    pv_cfg = config.get("pv") or {}
    if not pv_cfg.get("enabled"):
        raise HTTPException(status_code=404, detail="PV-Modul nicht aktiv")
    sensors = pv_cfg.get("sensors") or {}
    state = PvService().get_state(sensors)
    return {"state": state}


@router.get("/ha/pv/history")
def get_pv_history(view: str = Query("today")) -> dict[str, Any]:
    config = IntegrationConfigService().get_config()
    sensors = _pv_sensors(config)
    power_id = sensors.get("power", "")
    daily_id = sensors.get("daily", "")
    ha      = HomeAssistantProvider()
    now_loc = datetime.now(_LOCAL_TZ)                  # korrekte lokale Zeit via zoneinfo
    now_utc = now_loc.astimezone(timezone.utc)
    # Lokale Mitternacht → UTC
    start_utc = now_loc.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)

    # ── Heute: 5-Minuten-Leistungskurve ──────────────────────
    if view == "today":
        if not power_id:
            raise HTTPException(400, "Leistungs-Sensor nicht konfiguriert")

        # History API in 2h-Chunks (vermeidet Truncation bei vielen States)
        states = ha.get_history(power_id, start_utc, now_utc)
        labels, values = _history_to_5min_max(states)
        # Live-Wert als letzten Datenpunkt immer eintragen (überschreibt/ergänzt)
        live_state = ha.get_state(power_id)
        live_v = _safe_float((live_state or {}).get("state"))
        if live_v and live_v > 0:
            now_key = f"{now_loc.hour:02d}:{(now_loc.minute // 5) * 5:02d}"
            if labels and labels[-1] == now_key:
                values[-1] = max(values[-1] or 0, live_v)  # letzten Bucket aktualisieren
            else:
                labels.append(now_key)
                values.append(live_v)

        # Tagesertrag: direkt aus aktuellem Sensorwert (zuverlässiger als Statistics)
        total = None
        if daily_id:
            daily_state = ha.get_state(daily_id)
            if daily_state:
                total = _safe_float(daily_state.get("state"))

        return {"view": "today", "labels": labels, "values": values,
                "unit": "W", "total": total, "total_unit": "kWh"}

    # ── 7 Tage: Tagesertrag ───────────────────────────────────
    if view == "7days":
        if not daily_id:
            raise HTTPException(400, "Tagesertrag-Sensor nicht konfiguriert")
        s7_utc = (start_utc - timedelta(days=6))

        stats = ha.get_pv_statistics([daily_id], s7_utc, now_utc, "day", ["max"])
        rows  = stats.get(daily_id) or []
        if rows:
            labels, values = [], []
            for r in rows:
                dt = _to_local(r["start"])
                if dt:
                    labels.append(_DE_WEEKDAYS_SHORT[dt.weekday()])
                    values.append(_safe_float(r.get("max")))
        else:
            states = ha.get_history(daily_id, s7_utc, now_utc)
            daily  = _history_to_daily_max(states)
            labels, values = [], []
            for date_key in sorted(daily):
                dt = datetime.fromisoformat(date_key)
                labels.append(_DE_WEEKDAYS_SHORT[dt.weekday()])
                values.append(round(daily[date_key], 2))

        total = round(sum(v for v in values if v is not None), 1)
        return {"view": "7days", "labels": labels, "values": values,
                "unit": "kWh", "total": total, "total_unit": "kWh"}

    # ── Monat: alle Tage des Monats ───────────────────────────
    if view == "month":
        if not daily_id:
            raise HTTPException(400, "Tagesertrag-Sensor nicht konfiguriert")
        sm_utc = start_utc.replace(day=1)

        stats = ha.get_pv_statistics([daily_id], sm_utc, now_utc, "day", ["max"])
        rows  = stats.get(daily_id) or []
        if rows:
            labels, values = [], []
            for r in rows:
                dt = _to_local(r["start"])
                if dt:
                    labels.append(str(dt.day))
                    values.append(_safe_float(r.get("max")))
        else:
            states = ha.get_history(daily_id, sm_utc, now_utc)
            daily  = _history_to_daily_max(states)
            labels, values = [], []
            for date_key in sorted(daily):
                dt = datetime.fromisoformat(date_key)
                labels.append(str(dt.day))
                values.append(round(daily[date_key], 2))

        total = round(sum(v for v in values if v is not None), 1)
        return {"view": "month", "labels": labels, "values": values,
                "unit": "kWh", "total": total, "total_unit": "kWh"}

    # ── Jahr: Monatserträge ───────────────────────────────────
    if view == "year":
        if not daily_id:
            raise HTTPException(400, "Tagesertrag-Sensor nicht konfiguriert")
        sy_utc = start_utc.replace(month=1, day=1)

        stats = ha.get_pv_statistics([daily_id], sy_utc, now_utc, "month", ["sum"])
        rows  = stats.get(daily_id) or []
        if rows and any(r.get("sum") is not None for r in rows):
            labels, values = [], []
            for r in rows:
                dt = _to_local(r["start"])
                if dt:
                    labels.append(_DE_MONTHS_SHORT[dt.month - 1])
                    values.append(_safe_float(r.get("sum")))
        else:
            states = ha.get_history(daily_id, sy_utc, now_utc)
            daily  = _history_to_daily_max(states)
            monthly: dict[int, float] = defaultdict(float)
            for date_key, v in daily.items():
                monthly[int(date_key[5:7])] += v
            labels = [_DE_MONTHS_SHORT[m - 1] for m in sorted(monthly)]
            values = [round(monthly[m], 1) for m in sorted(monthly)]

        total = round(sum(v for v in values if v is not None), 1)
        return {"view": "year", "labels": labels, "values": values,
                "unit": "kWh", "total": total, "total_unit": "kWh"}

    raise HTTPException(400, f"Unbekannte View: {view}")
