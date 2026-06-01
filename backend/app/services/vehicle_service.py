from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.database.db import get_connection
from app.services.homeassistant_service import HomeAssistantService


class VehicleService:
    def __init__(self, ha: HomeAssistantService | None = None) -> None:
        self.ha = ha or HomeAssistantService()

    @staticmethod
    def default_vehicle() -> dict[str, Any]:
        return {
            "id": "fahrzeug_1",
            "label": "Fahrzeug 1",
            "enabled": True,
            "location_entity": "",
            "odometer_entity": "",
            "activity_entity": "",
            "ev_profile_enabled": False,
            "battery_entity": "",
            "range_entity": "",
            "fuel_level_entity": "",
            "adblue_level_entity": "",
            "charging_entity": "",
            "remaining_charge_time_entity": "",
            "plug_entity": "",
            "stop_charging_button_entity": "",
            "start_charging_button_entity": "",
            "climate_button_entity": "",
            "battery_capacity_kwh": None,
        }

    @staticmethod
    def from_ev_vehicle(vehicle: dict[str, Any]) -> dict[str, Any]:
        default = VehicleService.default_vehicle()
        merged = {**default, **(vehicle or {})}
        merged["enabled"] = True
        merged["ev_profile_enabled"] = True
        return merged

    def list_vehicles(self, config: dict[str, Any]) -> dict[str, Any]:
        vehicle_configs = self._vehicle_configs(config)
        vehicles = [self._resolve_vehicle(item) for item in vehicle_configs]
        vehicles = [item for item in vehicles if item]
        return {"enabled": bool((config.get("vehicles") or {}).get("enabled", True)), "vehicles": vehicles}

    def record_charging(self, config: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        cutoff_charging = now - timedelta(days=35)
        with get_connection() as conn:
            for vehicle_cfg in self._vehicle_configs(config):
                if not vehicle_cfg.get("enabled", True) or not vehicle_cfg.get("ev_profile_enabled"):
                    continue
                battery_entity = self._read_entity(vehicle_cfg.get("battery_entity"))
                if not battery_entity:
                    continue
                try:
                    battery_pct = float(battery_entity["state"])
                except (TypeError, ValueError):
                    continue
                charging_entity = self._read_entity(vehicle_cfg.get("charging_entity"))
                plug_entity = self._read_entity(vehicle_cfg.get("plug_entity"))
                is_charging = int(
                    (charging_entity or {}).get("state", "").lower()
                    in ("on", "charging", "in_charge", "true", "1")
                )
                plug_connected = int(
                    (plug_entity or {}).get("state", "").lower()
                    in ("on", "plugged_in", "connected", "true", "1", "charging", "in_charge")
                ) if plug_entity else is_charging
                try:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO vehicle_charging_history(
                            vehicle_id, battery_pct, is_charging, plug_connected, recorded_at, imported_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (vehicle_cfg["id"], battery_pct, is_charging, plug_connected,
                         now.replace(microsecond=0).isoformat(), now.isoformat()),
                    )
                except Exception:
                    pass
            conn.execute(
                "DELETE FROM vehicle_charging_history WHERE recorded_at < ?",
                (cutoff_charging.isoformat(),),
            )

    def charging_history(self, vehicle_id: str, period: str = "7days", battery_entity: str = "") -> dict[str, Any]:
        import os
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            tz = ZoneInfo(os.environ.get("TZ", "Europe/Berlin"))
        except ZoneInfoNotFoundError:
            tz = timezone.utc

        now = datetime.now(tz)
        if period == "month":
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            days_count = (now - start).days + 1
            labels   = [(start + timedelta(days=i)).strftime("%d.%m") for i in range(days_count)]
            day_keys = [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days_count)]
        else:
            start    = (now - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
            labels   = [(now - timedelta(days=6 - i)).strftime("%a %d.%m") for i in range(7)]
            day_keys = [(now - timedelta(days=6 - i)).strftime("%Y-%m-%d") for i in range(7)]

        start_utc = start.astimezone(timezone.utc)
        now_utc   = now.astimezone(timezone.utc)
        by_day: dict[str, list[float]] = {}

        # ── Primär: HA-History direkt abrufen ──────────────────
        if battery_entity:
            try:
                from app.search.providers.homeassistant import HomeAssistantProvider
                ha = HomeAssistantProvider()
                states = ha.get_history(battery_entity, start_utc, now_utc)
                for s in states:
                    try:
                        v = float(s.get("state", ""))
                    except (TypeError, ValueError):
                        continue
                    raw_ts = s.get("last_changed") or s.get("last_updated") or ""
                    try:
                        dt = datetime.fromisoformat(raw_ts)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        day = dt.astimezone(tz).strftime("%Y-%m-%d")
                    except Exception:
                        continue
                    by_day.setdefault(day, []).append(v)
            except Exception:
                pass

        # ── Fallback: lokale DB ─────────────────────────────────
        if not by_day:
            with get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT battery_pct, recorded_at FROM vehicle_charging_history
                    WHERE vehicle_id = ? AND recorded_at >= ?
                    ORDER BY recorded_at ASC
                    """,
                    (vehicle_id, start_utc.isoformat()),
                ).fetchall()
            for row in rows:
                try:
                    dt = datetime.fromisoformat(row["recorded_at"])
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    day = dt.astimezone(tz).strftime("%Y-%m-%d")
                except Exception:
                    continue
                by_day.setdefault(day, []).append(float(row["battery_pct"]))

        min_pct, max_pct, charged_pct = [], [], []
        for dk in day_keys:
            vals = by_day.get(dk, [])
            if vals:
                lo, hi = min(vals), max(vals)
                min_pct.append(round(lo, 1))
                max_pct.append(round(hi, 1))
                charged_pct.append(round(max(0.0, hi - lo), 1))
            else:
                min_pct.append(None)
                max_pct.append(None)
                charged_pct.append(None)

        return {
            "vehicle_id": vehicle_id,
            "period": period,
            "labels": labels,
            "min_pct": min_pct,
            "max_pct": max_pct,
            "charged_pct": charged_pct,
        }

    def record_locations(self, config: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=self._history_days(config))
        inserted = 0
        skipped = 0

        with get_connection() as conn:
            for vehicle_cfg in self._vehicle_configs(config):
                if not vehicle_cfg.get("enabled", True):
                    continue
                location = self._read_location(vehicle_cfg)
                if not location:
                    skipped += 1
                    continue

                latest = conn.execute(
                    """
                    SELECT latitude, longitude, recorded_at
                    FROM vehicle_location_history
                    WHERE vehicle_id = ?
                    ORDER BY recorded_at DESC
                    LIMIT 1
                    """,
                    (vehicle_cfg["id"],),
                ).fetchone()
                if latest and self._same_point(latest["latitude"], latest["longitude"], location["latitude"], location["longitude"]):
                    skipped += 1
                    continue

                conn.execute(
                    """
                    INSERT OR IGNORE INTO vehicle_location_history(
                        vehicle_id, vehicle_label, source_entity_id, latitude, longitude,
                        accuracy, speed, heading, state, recorded_at, imported_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        vehicle_cfg["id"],
                        vehicle_cfg["label"],
                        location["entity_id"],
                        location["latitude"],
                        location["longitude"],
                        location.get("accuracy"),
                        location.get("speed"),
                        location.get("heading"),
                        location.get("state"),
                        location["recorded_at"],
                        now.isoformat(),
                    ),
                )
                inserted += 1

            conn.execute(
                "DELETE FROM vehicle_location_history WHERE recorded_at < ?",
                (cutoff.isoformat(),),
            )

        return {"inserted": inserted, "skipped": skipped, "retention_days": self._history_days(config)}

    @staticmethod
    def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        from math import radians, sin, cos, sqrt, atan2
        R = 6_371_000
        φ1, φ2 = radians(lat1), radians(lat2)
        dφ = radians(lat2 - lat1)
        dλ = radians(lon2 - lon1)
        a = sin(dφ / 2) ** 2 + cos(φ1) * cos(φ2) * sin(dλ / 2) ** 2
        return R * 2 * atan2(sqrt(a), sqrt(1 - a))

    @staticmethod
    def _reverse_geocode(lat: float, lon: float) -> str:
        import json
        import time
        import urllib.request
        cache_key = f"geocode_{round(lat, 4)}_{round(lon, 4)}"
        with get_connection() as conn:
            cached = conn.execute(
                "SELECT value FROM system_state WHERE key = ?", (cache_key,)
            ).fetchone()
        if cached:
            try:
                return json.loads(cached["value"])
            except Exception:
                pass
        try:
            url = (
                f"https://nominatim.openstreetmap.org/reverse"
                f"?format=json&lat={lat}&lon={lon}&zoom=18&addressdetails=1"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "ErikaRobot/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            addr = data.get("address") or {}
            parts = [
                addr.get("road") or addr.get("pedestrian") or addr.get("path") or "",
                addr.get("house_number") or "",
                addr.get("city") or addr.get("town") or addr.get("village") or addr.get("municipality") or "",
            ]
            result = ", ".join(p for p in parts if p).strip(", ") or data.get("display_name", f"{lat:.4f}, {lon:.4f}")
            with get_connection() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO system_state(key, value) VALUES (?, ?)",
                    (cache_key, json.dumps(result)),
                )
            time.sleep(1.1)  # Nominatim rate limit: 1 req/s
            return result
        except Exception:
            return f"{lat:.4f}, {lon:.4f}"

    def location_history_clustered(self, vehicle_id: str, days: int = 14) -> dict[str, Any]:
        data = self.location_history(vehicle_id, days)
        points = data["points"]
        if not points:
            return {"vehicle_id": vehicle_id, "locations": []}

        clusters: list[dict[str, Any]] = []
        cur: dict[str, Any] | None = None
        THRESHOLD_M = 150

        for pt in points:
            lat, lon = pt["latitude"], pt["longitude"]
            if cur is None:
                cur = {"lat": lat, "lon": lon, "from": pt["recorded_at"],
                       "to": pt["recorded_at"], "count": 1}
            else:
                dist = self._haversine_m(cur["lat"], cur["lon"], lat, lon)
                if dist <= THRESHOLD_M:
                    cur["to"] = pt["recorded_at"]
                    cur["count"] += 1
                    cur["lat"] = (cur["lat"] * (cur["count"] - 1) + lat) / cur["count"]
                    cur["lon"] = (cur["lon"] * (cur["count"] - 1) + lon) / cur["count"]
                else:
                    clusters.append(cur)
                    cur = {"lat": lat, "lon": lon, "from": pt["recorded_at"],
                           "to": pt["recorded_at"], "count": 1}
        if cur:
            clusters.append(cur)

        # "to" eines Clusters = Zeitpunkt des ersten GPS-Punkts im NÄCHSTEN Cluster
        # → zeigt wann das Auto tatsächlich losgefahren ist, nicht wann der letzte Ping kam
        for i in range(len(clusters) - 1):
            clusters[i]["to"] = clusters[i + 1]["from"]

        locations = []
        for cl in clusters:
            try:
                from_dt = datetime.fromisoformat(cl["from"]).astimezone(timezone.utc)
                to_dt   = datetime.fromisoformat(cl["to"]).astimezone(timezone.utc)
                duration = int((to_dt - from_dt).total_seconds() / 60)
            except Exception:
                duration = 0
            address = self._reverse_geocode(cl["lat"], cl["lon"])
            locations.append({
                "address":          address,
                "lat":              round(cl["lat"], 5),
                "lon":              round(cl["lon"], 5),
                "from":             cl["from"],
                "to":               cl["to"],
                "duration_minutes": duration,
                "point_count":      cl["count"],
            })

        return {"vehicle_id": vehicle_id, "locations": list(reversed(locations))}

    def location_history(self, vehicle_id: str, days: int = 14) -> dict[str, Any]:
        safe_days = max(1, min(int(days or 14), 14))
        cutoff = datetime.now(timezone.utc) - timedelta(days=safe_days)
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT vehicle_id, vehicle_label, source_entity_id, latitude, longitude,
                       accuracy, speed, heading, state, recorded_at
                FROM vehicle_location_history
                WHERE vehicle_id = ? AND recorded_at >= ?
                ORDER BY recorded_at ASC
                """,
                (vehicle_id, cutoff.isoformat()),
            ).fetchall()
        return {
            "vehicle_id": vehicle_id,
            "days": safe_days,
            "points": [dict(row) for row in rows],
        }

    def _vehicle_configs(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        vehicles_cfg = config.get("vehicles") or {}
        configured = vehicles_cfg.get("items")
        if isinstance(configured, list) and configured:
            return [self._sanitize_vehicle(item, index) for index, item in enumerate(configured) if isinstance(item, dict)]

        ev_vehicles = (config.get("ev") or {}).get("vehicles") or []
        if ev_vehicles:
            return [self.from_ev_vehicle(item) for item in ev_vehicles if isinstance(item, dict)]
        return [self.default_vehicle()]

    def _resolve_vehicle(self, vehicle_cfg: dict[str, Any]) -> dict[str, Any] | None:
        if not vehicle_cfg.get("enabled", True):
            return None
        result = {
            "id": vehicle_cfg["id"],
            "label": vehicle_cfg["label"],
            "ev_profile_enabled": bool(vehicle_cfg.get("ev_profile_enabled", False)),
        }
        location = self._read_location(vehicle_cfg)
        if location:
            result["location"] = location
        odometer = self._read_entity(vehicle_cfg.get("odometer_entity"))
        if odometer:
            result["odometer"] = odometer
        activity = self._read_entity(vehicle_cfg.get("activity_entity"))
        if activity:
            result["activity"] = activity

        if result["ev_profile_enabled"]:
            for key, target in (
                ("battery_entity", "battery"),
                ("range_entity", "range"),
                ("charging_entity", "charging"),
                ("remaining_charge_time_entity", "remaining_charge_time"),
            ):
                entity = self._read_entity(vehicle_cfg.get(key))
                if entity:
                    result[target] = entity
            plug = self._read_entity(vehicle_cfg.get("plug_entity"))
            if plug:
                result["plug"] = plug
            result["stop_charging_button_entity"] = str(vehicle_cfg.get("stop_charging_button_entity") or "").strip()
            result["start_charging_button_entity"] = str(vehicle_cfg.get("start_charging_button_entity") or "").strip()
            cap = vehicle_cfg.get("battery_capacity_kwh")
            if cap is not None:
                try:
                    result["battery_capacity_kwh"] = float(cap)
                except (TypeError, ValueError):
                    pass
        else:
            for key, target in (
                ("fuel_level_entity", "fuel_level"),
                ("adblue_level_entity", "adblue_level"),
                ("range_entity", "range"),
            ):
                entity = self._read_entity(vehicle_cfg.get(key))
                if entity:
                    result[target] = entity

        result["climate_button_entity"] = str(vehicle_cfg.get("climate_button_entity") or "").strip()

        if len(result) <= 3:
            return None
        return result

    def _read_location(self, vehicle_cfg: dict[str, Any]) -> dict[str, Any] | None:
        entity_id = str(vehicle_cfg.get("location_entity") or "").strip()
        if not entity_id:
            return None
        state = self.ha.get_state(entity_id)
        if not state:
            return None
        attrs = state.get("attributes") or {}
        lat = self._float_or_none(attrs.get("latitude"))
        lon = self._float_or_none(attrs.get("longitude"))
        if lat is None or lon is None:
            return None
        return {
            "entity_id": entity_id,
            "latitude": lat,
            "longitude": lon,
            "accuracy": self._float_or_none(attrs.get("gps_accuracy")),
            "speed": self._float_or_none(attrs.get("speed")),
            "heading": self._float_or_none(attrs.get("course") or attrs.get("heading")),
            "state": state.get("state", ""),
            "recorded_at": state.get("last_updated") or state.get("last_changed") or datetime.now(timezone.utc).isoformat(),
        }

    def _read_entity(self, entity_id: Any) -> dict[str, Any] | None:
        entity_id = str(entity_id or "").strip()
        if not entity_id:
            return None
        state = self.ha.get_state(entity_id)
        if not state:
            return None
        raw = state.get("state")
        if raw in ("unavailable", "unknown", None, ""):
            return None
        attrs = state.get("attributes") or {}
        return {
            "entity_id": entity_id,
            "state": raw,
            "unit": attrs.get("unit_of_measurement", ""),
            "name": attrs.get("friendly_name", entity_id),
            "updated_at": state.get("last_updated") or state.get("last_changed"),
        }

    @staticmethod
    def sanitize_vehicle(item: dict[str, Any], index: int = 0) -> dict[str, Any]:
        return VehicleService._sanitize_vehicle(item, index)

    @staticmethod
    def _sanitize_vehicle(item: dict[str, Any], index: int = 0) -> dict[str, Any]:
        default = VehicleService.default_vehicle()
        label = str(item.get("label") or default["label"] or f"Fahrzeug {index + 1}").strip()
        vehicle_id = str(item.get("id") or label.lower().replace(" ", "_")).strip() or f"vehicle_{index + 1}"
        result = {**default, **item}
        result["id"] = vehicle_id
        result["label"] = label
        result["enabled"] = bool(item.get("enabled", True))
        result["ev_profile_enabled"] = bool(item.get("ev_profile_enabled", item.get("battery_entity") or item.get("range_entity")))
        for key in (
            "location_entity",
            "odometer_entity",
            "activity_entity",
            "battery_entity",
            "range_entity",
            "fuel_level_entity",
            "adblue_level_entity",
            "charging_entity",
            "remaining_charge_time_entity",
            "plug_entity",
            "stop_charging_button_entity",
            "start_charging_button_entity",
            "climate_button_entity",
        ):
            result[key] = str(result.get(key) or "").strip()
        cap = result.get("battery_capacity_kwh")
        if cap is not None:
            try:
                result["battery_capacity_kwh"] = float(cap)
            except (TypeError, ValueError):
                result["battery_capacity_kwh"] = None
        return result

    @staticmethod
    def _history_days(config: dict[str, Any]) -> int:
        try:
            days = int((config.get("vehicles") or {}).get("location_history_days", 14))
        except (TypeError, ValueError):
            days = 14
        return max(1, min(days, 14))

    @staticmethod
    def _same_point(a_lat: Any, a_lon: Any, b_lat: float, b_lon: float) -> bool:
        try:
            return round(float(a_lat), 6) == round(float(b_lat), 6) and round(float(a_lon), 6) == round(float(b_lon), 6)
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _float_or_none(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
