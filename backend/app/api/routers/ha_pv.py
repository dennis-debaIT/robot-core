from __future__ import annotations

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
        return f if f == f else None  # NaN check
    except (TypeError, ValueError):
        return None


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
    ha = HomeAssistantProvider()
    now = datetime.now(timezone.utc)

    if view == "today":
        if not power_id:
            raise HTTPException(400, "Leistungs-Sensor nicht konfiguriert")
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        stats = ha.get_pv_statistics([power_id], start, now, "hour", ["mean"])
        rows = stats.get(power_id) or []
        labels, values = [], []
        for row in rows:
            dt = datetime.fromisoformat(row["start"])
            labels.append(f"{dt.hour:02d}:00")
            values.append(_safe_float(row.get("mean")))
        total = None
        if daily_id:
            s2 = ha.get_pv_statistics([daily_id], start, now, "hour", ["max"])
            last = (s2.get(daily_id) or [{}])[-1]
            total = _safe_float(last.get("max"))
        return {"view": "today", "labels": labels, "values": values,
                "unit": "W", "total": total, "total_unit": "kWh"}

    if view == "7days":
        if not daily_id:
            raise HTTPException(400, "Tagesertrag-Sensor nicht konfiguriert")
        start = (now - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
        stats = ha.get_pv_statistics([daily_id], start, now, "day", ["max"])
        rows = stats.get(daily_id) or []
        labels, values = [], []
        for row in rows:
            dt = datetime.fromisoformat(row["start"])
            labels.append(_DE_WEEKDAYS_SHORT[dt.weekday()])
            values.append(_safe_float(row.get("max")))
        total = sum(v for v in values if v is not None)
        return {"view": "7days", "labels": labels, "values": values,
                "unit": "kWh", "total": round(total, 1), "total_unit": "kWh"}

    if view == "month":
        if not daily_id:
            raise HTTPException(400, "Tagesertrag-Sensor nicht konfiguriert")
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        stats = ha.get_pv_statistics([daily_id], start, now, "day", ["max"])
        rows = stats.get(daily_id) or []
        labels, values = [], []
        for row in rows:
            dt = datetime.fromisoformat(row["start"])
            labels.append(str(dt.day))
            values.append(_safe_float(row.get("max")))
        total = sum(v for v in values if v is not None)
        return {"view": "month", "labels": labels, "values": values,
                "unit": "kWh", "total": round(total, 1), "total_unit": "kWh"}

    if view == "year":
        if not daily_id:
            raise HTTPException(400, "Tagesertrag-Sensor nicht konfiguriert")
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        stats = ha.get_pv_statistics([daily_id], start, now, "month", ["sum"])
        rows = stats.get(daily_id) or []
        # Fallback: aggregate daily if monthly sum unavailable
        if not rows:
            stats2 = ha.get_pv_statistics([daily_id], start, now, "day", ["max"])
            from collections import defaultdict
            monthly: dict[int, float] = defaultdict(float)
            for row in stats2.get(daily_id) or []:
                dt = datetime.fromisoformat(row["start"])
                v = _safe_float(row.get("max"))
                if v is not None:
                    monthly[dt.month] += v
            labels = [_DE_MONTHS_SHORT[m - 1] for m in sorted(monthly)]
            values = [round(monthly[m], 1) for m in sorted(monthly)]
        else:
            labels, values = [], []
            for row in rows:
                dt = datetime.fromisoformat(row["start"])
                labels.append(_DE_MONTHS_SHORT[dt.month - 1])
                values.append(_safe_float(row.get("sum")))
        total = sum(v for v in values if v is not None)
        return {"view": "year", "labels": labels, "values": values,
                "unit": "kWh", "total": round(total, 1), "total_unit": "kWh"}

    raise HTTPException(400, f"Unbekannte View: {view}")
