"""Stromkosten-Endpunkte — Netzbezug + einzelne Verbrauchssensoren ("Strom").

Verbrauch (kWh) ist in allen Editionen sichtbar. Die Kostenberechnung (€)
wird hier ebenfalls immer mitgeliefert (Local-First: Rohdaten/Endpunkte
bleiben frei) — das Frontend blendet die Kosten-Anzeige für Community aus
(Feature `energy_costs`, siehe feature_service.py).
"""
from __future__ import annotations

import calendar
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query

from app.search.providers.homeassistant import HomeAssistantProvider
from app.services.integration_config_service import IntegrationConfigService

router = APIRouter()

_DE_WEEKDAYS_SHORT = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
_DE_MONTHS_SHORT   = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
                       "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]

try:
    _LOCAL_TZ = ZoneInfo(os.environ.get("TZ", "Europe/Berlin"))
except ZoneInfoNotFoundError:
    _LOCAL_TZ = ZoneInfo("UTC")


def _safe_float(v: Any) -> float | None:
    try:
        f = float(v)
        return None if f != f else f  # NaN → None
    except (TypeError, ValueError):
        return None


def _energy_sensors(config: dict) -> list[dict[str, str]]:
    return (config.get("energy") or {}).get("sensors") or []


def _energy_tariffs(config: dict) -> tuple[float, float, float, float]:
    """Liefert (Einspeiseverguetung ct/kWh, Strombezugstarif ct/kWh,
    Grundpreis €/Jahr brutto, weitere feste Gebühren €/Jahr brutto)."""
    tariffs = (config.get("energy") or {}).get("tariffs") or {}
    feed_in_ct = _safe_float(tariffs.get("feed_in_ct")) or 0.0
    grid_price_ct = _safe_float(tariffs.get("grid_price_ct")) or 0.0
    base_price_eur_year = _safe_float(tariffs.get("base_price_eur_year")) or 0.0
    extra_fees_eur_year = _safe_float(tariffs.get("extra_fees_eur_year")) or 0.0
    return feed_in_ct, grid_price_ct, base_price_eur_year, extra_fees_eur_year


def _stat_to_local(raw: Any) -> datetime | None:
    """Konvertiert einen Statistik-Zeitstempel (Epoch-ms aus der WS-API oder
    ISO-String) in lokale Zeit via zoneinfo."""
    try:
        if isinstance(raw, (int, float)):
            dt = datetime.fromtimestamp(raw / 1000, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_LOCAL_TZ).replace(tzinfo=None)
    except Exception:
        return None


def _watts_scale(ha: "HomeAssistantProvider", entity_id: str) -> float:
    """Ermittelt den Umrechnungsfaktor auf Watt für einen Leistungssensor.

    Die Integrationsformel unten rechnet fest in W → kWh; Sensoren, die
    stattdessen in kW melden (z.B. manche Wallbox-/SDongle-Sensoren, im
    Unterschied zu den bisherigen W-Sensoren wie dem Netzzähler), würden ohne
    diese Normalisierung um Faktor 1000 zu niedrig berechnet. Fällt auf 1.0
    (Watt, bisheriges Verhalten) zurück wenn die Einheit nicht ermittelbar ist."""
    try:
        state = ha.get_state(entity_id)
        unit = ((state or {}).get("attributes") or {}).get("unit_of_measurement", "")
        return 1000.0 if str(unit).strip().lower() == "kw" else 1.0
    except Exception:
        return 1.0


def _integrate_power_daily_from_history(
    entity_id: str,
    start_utc: datetime,
    end_utc: datetime,
    ha: "HomeAssistantProvider",
    signed: bool,
    scale: float = 1.0,
    min_power_w: float = 0.0,
) -> dict[str, dict[str, float]]:
    """Trennt einen Leistungssensor (W) in tägliche Einspeisung und Netzbezug (kWh).

    signed=True: positiv = Einspeisung (Export), negativ = Netzbezug (Import)
    — Huawei-Konvention (Netzbezugs-Sensor). signed=False: alle Werte gelten
    als Verbrauch/Netzbezug, Einspeisung bleibt 0 (Gerätesensor).
    Greift auf die Rohzustands-History zu (1 API-Aufruf pro 24h-Chunk).
    scale normalisiert Sensoren, die nicht in W melden (siehe _watts_scale).
    min_power_w (nur bei Gerätesensoren, signed=False): Werte darunter zählen
    nicht als Verbrauch — trennt z.B. die Standby-Last einer Wallbox
    (durchgehend ein paar hundert Watt) von echtem Laden."""
    states = ha.get_history(entity_id, start_utc, end_utc, chunk_hours=24)

    by_date: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for s in states:
        v = _safe_float(s.get("state"))
        if v is None:
            continue
        v *= scale
        if not signed and v < 0:
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
        by_date[dt_loc.strftime("%Y-%m-%d")].append((dt_utc.timestamp(), v))

    result: dict[str, dict[str, float]] = {}
    for date_key, readings in by_date.items():
        readings.sort(key=lambda x: x[0])
        ein = 0.0
        bez = 0.0
        for i in range(len(readings) - 1):
            dt_secs = readings[i + 1][0] - readings[i][0]
            if 0 < dt_secs <= 1800:
                v_i = readings[i][1]
                if not signed and min_power_w > 0 and v_i < min_power_w:
                    continue  # Standby/Leerlauf unterhalb der Schwelle zählt nicht
                kwh = v_i * dt_secs / 3_600_000
                if signed:
                    if kwh > 0:
                        ein += kwh   # positiv = Einspeisung
                    else:
                        bez -= kwh   # negativ → positiver Bezugswert
                else:
                    bez += kwh       # Gerätesensor: alles Verbrauch
        result[date_key] = {"einspeisung": round(ein, 2), "netzbezug": round(bez, 2)}

    return result


async def _integrate_power_daily_from_stats(
    entity_id: str,
    start_utc: datetime,
    end_utc: datetime,
    ha: "HomeAssistantProvider",
    signed: bool,
    scale: float = 1.0,
    min_power_w: float = 0.0,
) -> dict[str, dict[str, float]]:
    """Wie _integrate_power_daily_from_history, aber aus der HA-Langzeitstatistik
    (stündliche Mittelwerte) — 1 API-Aufruf statt einem pro Tag.

    Liefert {} wenn der Sensor keine Langzeitstatistik führt; dann greift der
    History-Fallback. scale normalisiert Sensoren, die nicht in W melden
    (siehe _watts_scale). min_power_w siehe _integrate_power_daily_from_history."""
    stats = await ha.get_pv_statistics([entity_id], start_utc, end_utc, "hour", ["mean"])
    rows = stats.get(entity_id) or []
    if not rows:
        return {}

    result: dict[str, dict[str, float]] = {}
    for r in rows:
        mean_w = _safe_float(r.get("mean"))
        if mean_w is None:
            continue
        mean_w *= scale
        if not signed and mean_w < 0:
            continue
        if not signed and min_power_w > 0 and mean_w < min_power_w:
            continue
        dt_loc = _stat_to_local(r.get("start"))
        if not dt_loc:
            continue
        bucket = result.setdefault(dt_loc.strftime("%Y-%m-%d"), {"einspeisung": 0.0, "netzbezug": 0.0})
        kwh = mean_w / 1000  # mean_W über 1h → kWh
        if signed:
            if kwh > 0:
                bucket["einspeisung"] += kwh
            else:
                bucket["netzbezug"] -= kwh
        else:
            bucket["netzbezug"] += kwh

    for v in result.values():
        v["einspeisung"] = round(v["einspeisung"], 2)
        v["netzbezug"] = round(v["netzbezug"], 2)
    return result


async def _integrate_power_daily(
    entity_id: str,
    start_utc: datetime,
    end_utc: datetime,
    ha: "HomeAssistantProvider",
    signed: bool,
    min_power_w: float = 0.0,
) -> dict[str, dict[str, float]]:
    """Trennt einen Leistungssensor (W) in tägliche Einspeisung und Netzbezug (kWh).

    Für Zeiträume über ~1 Tag wird die HA-Langzeitstatistik genutzt (1 API-Aufruf
    statt einem pro Tag). Der heutige Tag wird per History nachgeladen, da die
    Statistik die laufende Stunde noch nicht enthält.
    """
    now_loc = datetime.now(_LOCAL_TZ)
    today_start_utc = now_loc.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    scale = _watts_scale(ha, entity_id)

    if (end_utc - start_utc) <= timedelta(hours=36):
        return _integrate_power_daily_from_history(entity_id, start_utc, end_utc, ha, signed, scale, min_power_w)

    result = await _integrate_power_daily_from_stats(entity_id, start_utc, end_utc, ha, signed, scale, min_power_w)
    if not result:
        return _integrate_power_daily_from_history(entity_id, start_utc, end_utc, ha, signed, scale, min_power_w)

    if end_utc > today_start_utc:
        today = _integrate_power_daily_from_history(entity_id, max(start_utc, today_start_utc), end_utc, ha, signed, scale, min_power_w)
        result.update(today)

    return result


def _fixed_costs(start: datetime, end: datetime, annual_eur: float) -> float:
    """Verteilt einen jährlichen Brutto-Fixbetrag (Grundpreis + weitere Gebühren)
    auf den Zeitraum [start, end] (inklusive, lokale Tage), unter Berücksichtigung
    von Schaltjahren — analog zur Tagesanteil-Berechnung auf Stromrechnungen."""
    if annual_eur <= 0:
        return 0.0
    total = 0.0
    d = start.date()
    end_date = end.date()
    while d <= end_date:
        days_in_year = 366 if calendar.isleap(d.year) else 365
        total += annual_eur / days_in_year
        d += timedelta(days=1)
    return round(total, 2)


def _energy_costs(ein_kwh: float, bez_kwh: float, feed_in_ct: float, grid_price_ct: float, fixed_costs: float = 0.0) -> dict[str, float]:
    """Berechnet Einspeiseerlös, Netzbezugskosten und Saldo (€) aus kWh, Cent/kWh-Tarifen
    und anteiligen Fixkosten (Grundpreis + weitere Gebühren) für den Zeitraum."""
    einspeisung_value = round(ein_kwh * feed_in_ct / 100, 2)
    netzbezug_cost    = round(bez_kwh * grid_price_ct / 100, 2)
    result = {
        "einspeisung_value": einspeisung_value,
        "netzbezug_cost":    netzbezug_cost,
        "saldo":             round(einspeisung_value - netzbezug_cost - fixed_costs, 2),
    }
    if fixed_costs:
        result["fixed_costs"] = fixed_costs
    return result


def _daily_series(daily: dict[str, dict[str, float]], label_fn: Callable[[datetime], str]) -> tuple[list[str], list[float], list[float]]:
    labels, ein_vals, bez_vals = [], [], []
    for date_key in sorted(daily):
        dt = datetime.fromisoformat(date_key)
        labels.append(label_fn(dt))
        ein_vals.append(daily[date_key]["einspeisung"])
        bez_vals.append(daily[date_key]["netzbezug"])
    return labels, ein_vals, bez_vals


def _monthly_series(daily: dict[str, dict[str, float]]) -> tuple[list[str], list[float], list[float]]:
    monthly_ein: dict[int, float] = defaultdict(float)
    monthly_bez: dict[int, float] = defaultdict(float)
    for date_key, v in daily.items():
        m = int(date_key[5:7])
        monthly_ein[m] += v["einspeisung"]
        monthly_bez[m] += v["netzbezug"]
    months = sorted(set(list(monthly_ein) + list(monthly_bez)))
    labels   = [_DE_MONTHS_SHORT[m - 1] for m in months]
    ein_vals = [round(monthly_ein[m], 1) for m in months]
    bez_vals = [round(monthly_bez[m], 1) for m in months]
    return labels, ein_vals, bez_vals


@router.get("/ha/energy/history")
async def get_energy_history(view: str = Query("today")) -> dict[str, Any]:
    config = IntegrationConfigService().get_config()
    sensors_cfg = _energy_sensors(config)
    if not sensors_cfg:
        raise HTTPException(404, "Keine Energie-Sensoren konfiguriert")

    feed_in_ct, grid_price_ct, base_price_eur_year, extra_fees_eur_year = _energy_tariffs(config)
    annual_fixed_eur = base_price_eur_year + extra_fees_eur_year
    costs_enabled = feed_in_ct > 0 or grid_price_ct > 0 or annual_fixed_eur > 0

    ha      = HomeAssistantProvider()
    now_loc = datetime.now(_LOCAL_TZ)
    now_utc = now_loc.astimezone(timezone.utc)
    start_utc = now_loc.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)

    if view == "today":
        period_start_utc = start_utc
    elif view == "7days":
        period_start_utc = start_utc - timedelta(days=6)
    elif view == "month":
        period_start_utc = now_loc.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    elif view == "year":
        period_start_utc = now_loc.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    else:
        raise HTTPException(400, f"Unbekannte View: {view}")

    period_start_loc = now_loc if view == "today" else period_start_utc.astimezone(_LOCAL_TZ)

    result_sensors: list[dict[str, Any]] = []
    for sensor in sensors_cfg:
        signed = sensor.get("role") == "grid"
        min_power_w = _safe_float(sensor.get("min_power_w")) or 0.0
        daily = await _integrate_power_daily(sensor["entity_id"], period_start_utc, now_utc, ha, signed, min_power_w)

        entry: dict[str, Any] = {
            "id": sensor["id"], "label": sensor["label"], "role": sensor.get("role", "device"), "unit": "kWh",
        }

        if view == "today":
            today = daily.get(now_loc.strftime("%Y-%m-%d"), {"einspeisung": 0.0, "netzbezug": 0.0})
            if signed:
                entry["einspeisung"] = today["einspeisung"]
                entry["netzbezug"] = today["netzbezug"]
                if costs_enabled:
                    fixed = _fixed_costs(now_loc, now_loc, annual_fixed_eur)
                    entry["costs"] = _energy_costs(today["einspeisung"], today["netzbezug"], feed_in_ct, grid_price_ct, fixed)
            else:
                entry["verbrauch"] = today["netzbezug"]
                if grid_price_ct > 0:
                    entry["cost"] = round(today["netzbezug"] * grid_price_ct / 100, 2)
        else:
            if view == "7days":
                labels, ein_vals, bez_vals = _daily_series(daily, lambda dt: _DE_WEEKDAYS_SHORT[dt.weekday()])
            elif view == "month":
                labels, ein_vals, bez_vals = _daily_series(daily, lambda dt: str(dt.day))
            else:  # year
                labels, ein_vals, bez_vals = _monthly_series(daily)

            ein_total = round(sum(ein_vals), 1)
            bez_total = round(sum(bez_vals), 1)

            if signed:
                entry["labels"] = labels
                entry["einspeisung"] = ein_vals
                entry["netzbezug"] = bez_vals
                entry["einspeisung_total"] = ein_total
                entry["netzbezug_total"] = bez_total
                if costs_enabled:
                    fixed = _fixed_costs(period_start_loc, now_loc, annual_fixed_eur)
                    entry["costs"] = _energy_costs(ein_total, bez_total, feed_in_ct, grid_price_ct, fixed)
            else:
                entry["labels"] = labels
                entry["verbrauch"] = bez_vals
                entry["verbrauch_total"] = bez_total
                if grid_price_ct > 0:
                    entry["cost"] = round(bez_total * grid_price_ct / 100, 2)

        result_sensors.append(entry)

    return {"view": view, "sensors": result_sensors}
