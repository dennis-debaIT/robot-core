from __future__ import annotations

import calendar
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


def _integrate_power_to_daily_kwh(
    power_id: str,
    start_utc: datetime,
    end_utc: datetime,
    ha: "HomeAssistantProvider",
) -> dict[str, float]:
    """Leitet Tageserträge (kWh) aus einem Leistungssensor (W) ab.

    Nutzt 24h-Chunks statt 2h — reduziert API-Aufrufe für Mehrtageszeiträume
    erheblich. Für Sensoren mit sehr hoher Update-Frequenz (< 1/min) können
    Randwerte leicht unterschätzt werden; für typische PV-Wechselrichter (5-15 min)
    ist die Genauigkeit ausreichend.
    """
    states = ha.get_history(power_id, start_utc, end_utc, chunk_hours=24)

    # Zeitstempel → epoch für präzise Δt-Berechnung
    by_date: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for s in states:
        v = _safe_float(s.get("state"))
        if v is None or v < 0:
            continue
        ts_str = s.get("last_changed") or s.get("last_updated") or ""
        if not ts_str:
            continue
        try:
            dt_utc = datetime.fromisoformat(ts_str)
            if dt_utc.tzinfo is None:
                dt_utc = dt_utc.replace(tzinfo=timezone.utc)
            dt_loc = dt_utc.astimezone(_LOCAL_TZ)
        except Exception:
            continue
        date_key = dt_loc.strftime("%Y-%m-%d")
        by_date[date_key].append((dt_utc.timestamp(), v))

    result: dict[str, float] = {}
    for date_key, readings in by_date.items():
        readings.sort(key=lambda x: x[0])
        kwh = 0.0
        for i in range(len(readings) - 1):
            dt_secs = readings[i + 1][0] - readings[i][0]
            # Lücken > 30 min ignorieren (Nacht, Ausfall) um Überschätzung zu vermeiden
            if 0 < dt_secs <= 1800:
                kwh += readings[i][1] * dt_secs / 3_600_000  # W·s → kWh
        result[date_key] = round(kwh, 2)

    return result


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

        # Tagesertrag: aus dediziertem Sensor (bevorzugt) oder via Integration
        total = None
        if daily_id:
            daily_state = ha.get_state(daily_id)
            if daily_state:
                total = _safe_float(daily_state.get("state"))
        if total is None:
            # Tagesertrag aus der bereits geladenen Leistungshistorie ableiten
            today_str = now_loc.strftime("%Y-%m-%d")
            today_kwh = _integrate_power_to_daily_kwh(power_id, start_utc, now_utc, ha)
            total = today_kwh.get(today_str)

        return {"view": "today", "labels": labels, "values": values,
                "unit": "W", "total": total, "total_unit": "kWh"}

    # ── 7 Tage: Tagesertrag ───────────────────────────────────
    if view == "7days":
        if not daily_id and not power_id:
            raise HTTPException(400, "Leistungs- oder Tagesertrag-Sensor nicht konfiguriert")
        s7_utc = (start_utc - timedelta(days=6))

        if daily_id:
            stats = ha.get_pv_statistics([daily_id], s7_utc, now_utc, "day", ["max"])
            rows  = stats.get(daily_id) or []
            if rows:
                daily: dict[str, float] = {}
                for r in rows:
                    dt = _to_local(r["start"])
                    if dt:
                        daily[dt.strftime("%Y-%m-%d")] = _safe_float(r.get("max")) or 0.0
            else:
                states = ha.get_history(daily_id, s7_utc, now_utc)
                daily = _history_to_daily_max(states)
        else:
            # Ableitung aus Leistungssensor (W → kWh via Integration)
            daily = _integrate_power_to_daily_kwh(power_id, s7_utc, now_utc, ha)

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
        if not daily_id and not power_id:
            raise HTTPException(400, "Leistungs- oder Tagesertrag-Sensor nicht konfiguriert")
        sm_utc = start_utc.replace(day=1)

        if daily_id:
            stats = ha.get_pv_statistics([daily_id], sm_utc, now_utc, "day", ["max"])
            rows  = stats.get(daily_id) or []
            if rows:
                daily_m: dict[str, float] = {}
                for r in rows:
                    dt = _to_local(r["start"])
                    if dt:
                        daily_m[dt.strftime("%Y-%m-%d")] = _safe_float(r.get("max")) or 0.0
            else:
                states = ha.get_history(daily_id, sm_utc, now_utc)
                daily_m = _history_to_daily_max(states)
        else:
            daily_m = _integrate_power_to_daily_kwh(power_id, sm_utc, now_utc, ha)

        labels, values = [], []
        for date_key in sorted(daily_m):
            dt = datetime.fromisoformat(date_key)
            labels.append(str(dt.day))
            values.append(round(daily_m[date_key], 2))

        total = round(sum(v for v in values if v is not None), 1)
        return {"view": "month", "labels": labels, "values": values,
                "unit": "kWh", "total": total, "total_unit": "kWh"}

    # ── Jahr: Monatserträge ───────────────────────────────────
    if view == "year":
        if not daily_id and not power_id:
            raise HTTPException(400, "Leistungs- oder Tagesertrag-Sensor nicht konfiguriert")
        sy_utc = start_utc.replace(month=1, day=1)

        if daily_id:
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
                daily_y = _history_to_daily_max(states)
                monthly: dict[int, float] = defaultdict(float)
                for date_key, v in daily_y.items():
                    monthly[int(date_key[5:7])] += v
                labels = [_DE_MONTHS_SHORT[m - 1] for m in sorted(monthly)]
                values = [round(monthly[m], 1) for m in sorted(monthly)]
        else:
            # Ableitung aus Leistungssensor: HA-Statistics mit "mean" (1 API-Aufruf)
            # → mean_W × Stunden_im_Monat / 1000 = kWh
            stats = ha.get_pv_statistics([power_id], sy_utc, now_utc, "month", ["mean"])
            rows  = stats.get(power_id) or []
            if rows and any(r.get("mean") is not None for r in rows):
                labels, values = [], []
                for r in rows:
                    dt = _to_local(r["start"])
                    if dt:
                        mean_w = _safe_float(r.get("mean"))
                        hours = calendar.monthrange(dt.year, dt.month)[1] * 24
                        kwh = round(mean_w * hours / 1000, 1) if mean_w is not None else None
                        labels.append(_DE_MONTHS_SHORT[dt.month - 1])
                        values.append(kwh)
            else:
                # Letzter Fallback: Tagesintegration → monatliche Summen
                daily_y = _integrate_power_to_daily_kwh(power_id, sy_utc, now_utc, ha)
                monthly = defaultdict(float)
                for date_key, v in daily_y.items():
                    monthly[int(date_key[5:7])] += v
                labels = [_DE_MONTHS_SHORT[m - 1] for m in sorted(monthly)]
                values = [round(monthly[m], 1) for m in sorted(monthly)]

        total = round(sum(v for v in values if v is not None), 1)
        return {"view": "year", "labels": labels, "values": values,
                "unit": "kWh", "total": total, "total_unit": "kWh"}

    raise HTTPException(400, f"Unbekannte View: {view}")
