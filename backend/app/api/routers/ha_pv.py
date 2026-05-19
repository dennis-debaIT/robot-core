from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.search.providers.homeassistant import HomeAssistantProvider
from app.services.integration_config_service import IntegrationConfigService
from app.services.pv_service import PV_PROVIDERS, PvService

router = APIRouter()

_DE_WEEKDAYS_SHORT = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
_DE_MONTHS_SHORT   = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
                       "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]


def _pv_sensors(config: dict) -> dict[str, str]:
    return (config.get("pv") or {}).get("sensors") or {}


def _safe_float(v: Any) -> float | None:
    try:
        f = float(v)
        return None if f != f else f  # NaN → None
    except (TypeError, ValueError):
        return None


def _history_to_5min_mean(states: list[dict]) -> tuple[list[str], list[float | None]]:
    """Aggregiert Rohzustände zu 5-Minuten-Mittelwerten."""
    buckets: dict[str, list[float]] = defaultdict(list)
    for s in states:
        v = _safe_float(s.get("state"))
        if v is None:
            continue
        raw = s.get("last_changed") or s.get("last_updated") or ""
        try:
            dt = datetime.fromisoformat(raw[:19])
            total_min = dt.hour * 60 + dt.minute
            bucket = (total_min // 5) * 5
            key = f"{bucket // 60:02d}:{bucket % 60:02d}"
            buckets[key].append(v)
        except Exception:
            pass
    labels, values = [], []
    for key in sorted(buckets):
        labels.append(key)
        vals = buckets[key]
        values.append(round(sum(vals) / len(vals), 1) if vals else None)
    return labels, values


def _history_to_daily_max(states: list[dict]) -> dict[str, float]:
    """Liefert {date_str: max_value} aus Rohzuständen."""
    daily: dict[str, float] = {}
    for s in states:
        v = _safe_float(s.get("state"))
        if v is None:
            continue
        raw = s.get("last_changed") or s.get("last_updated") or ""
        try:
            date_key = raw[:10]
            daily[date_key] = max(daily.get(date_key, 0.0), v)
        except Exception:
            pass
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
    ha  = HomeAssistantProvider()
    now = datetime.now(timezone.utc)

    # ── Heute: stündliche Leistungskurve ──────────────────────
    if view == "today":
        if not power_id:
            raise HTTPException(400, "Leistungs-Sensor nicht konfiguriert")
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Primär: Statistics API (5-Minuten-Auflösung)
        stats = ha.get_pv_statistics([power_id], start, now, "5minute", ["mean"])
        rows  = stats.get(power_id) or []
        if rows:
            labels, values = [], []
            for row in rows:
                dt = datetime.fromisoformat(row["start"])
                labels.append(f"{dt.hour:02d}:{dt.minute:02d}")
                values.append(_safe_float(row.get("mean")))
        else:
            # Fallback: History API → 5-Minuten-Buckets
            states = ha.get_history(power_id, start, now)
            labels, values = _history_to_5min_mean(states)

        total = None
        if daily_id:
            s2   = ha.get_pv_statistics([daily_id], start, now, "hour", ["max"])
            last = (s2.get(daily_id) or [{}])[-1]
            total = _safe_float(last.get("max"))
            if total is None:
                states2 = ha.get_history(daily_id, start, now)
                dm = _history_to_daily_max(states2)
                total = max(dm.values()) if dm else None

        return {"view": "today", "labels": labels, "values": values,
                "unit": "W", "total": total, "total_unit": "kWh"}

    # ── 7 Tage: Tagesertrag ───────────────────────────────────
    if view == "7days":
        if not daily_id:
            raise HTTPException(400, "Tagesertrag-Sensor nicht konfiguriert")
        start = (now - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)

        stats = ha.get_pv_statistics([daily_id], start, now, "day", ["max"])
        rows  = stats.get(daily_id) or []
        if rows:
            labels = [_DE_WEEKDAYS_SHORT[datetime.fromisoformat(r["start"]).weekday()] for r in rows]
            values = [_safe_float(r.get("max")) for r in rows]
        else:
            states = ha.get_history(daily_id, start, now)
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
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        stats = ha.get_pv_statistics([daily_id], start, now, "day", ["max"])
        rows  = stats.get(daily_id) or []
        if rows:
            labels = [str(datetime.fromisoformat(r["start"]).day) for r in rows]
            values = [_safe_float(r.get("max")) for r in rows]
        else:
            states = ha.get_history(daily_id, start, now)
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
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

        # Primär: monthly statistics
        stats = ha.get_pv_statistics([daily_id], start, now, "month", ["sum"])
        rows  = stats.get(daily_id) or []
        if rows and any(r.get("sum") is not None for r in rows):
            labels = [_DE_MONTHS_SHORT[datetime.fromisoformat(r["start"]).month - 1] for r in rows]
            values = [_safe_float(r.get("sum")) for r in rows]
        else:
            # Fallback: tägliche History → nach Monat aggregieren
            states = ha.get_history(daily_id, start, now)
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
