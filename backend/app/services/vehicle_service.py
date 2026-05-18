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
            "stop_charging_button_entity": "",
            "climate_button_entity": "",
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
            result["stop_charging_button_entity"] = str(vehicle_cfg.get("stop_charging_button_entity") or "").strip()
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
            "stop_charging_button_entity",
            "climate_button_entity",
        ):
            result[key] = str(result.get(key) or "").strip()
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
