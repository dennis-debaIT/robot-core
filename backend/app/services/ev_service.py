from __future__ import annotations

from typing import Any

from app.services.homeassistant_service import HomeAssistantService


class EvService:
    _FIELD_LABELS = {
        "battery_entity": "Batterie",
        "range_entity": "Reichweite",
        "charging_entity": "Ladestatus",
        "remaining_charge_time_entity": "Restladezeit",
        "stop_charging_button_entity": "Laden stoppen",
    }

    def __init__(self, ha: HomeAssistantService | None = None) -> None:
        self.ha = ha or HomeAssistantService()

    @staticmethod
    def default_vehicle() -> dict[str, Any]:
        return {
            "id": "dacia_spring",
            "label": "Dacia Spring",
            "battery_entity": "sensor.batterie",
            "range_entity": "sensor.batteriereichweite",
            "charging_entity": "binary_sensor.ladestatus",
            "remaining_charge_time_entity": "sensor.verbleibende_ladezeit",
            "stop_charging_button_entity": "button.ladevorgang_stoppen",
        }

    def entity_options(self) -> list[dict[str, Any]]:
        options: list[dict[str, Any]] = []
        for state in self.ha.get_states():
            entity_id = state.get("entity_id", "")
            if not entity_id.startswith(("sensor.", "binary_sensor.", "button.")):
                continue
            attrs = state.get("attributes", {})
            options.append(
                {
                    "entity_id": entity_id,
                    "name": attrs.get("friendly_name", entity_id),
                    "state": state.get("state", ""),
                    "domain": entity_id.split(".", 1)[0],
                    "unit": attrs.get("unit_of_measurement", ""),
                }
            )
        return sorted(options, key=lambda item: (item["domain"], item["name"].lower()))

    def field_options(self) -> dict[str, list[dict[str, Any]]]:
        options = self.entity_options()
        return {
            "battery_entity": [item for item in options if item["domain"] == "sensor"],
            "range_entity": [item for item in options if item["domain"] == "sensor"],
            "charging_entity": [item for item in options if item["domain"] in ("binary_sensor", "sensor")],
            "remaining_charge_time_entity": [item for item in options if item["domain"] == "sensor"],
            "stop_charging_button_entity": [item for item in options if item["domain"] == "button"],
        }

    def display_data(self, config: dict[str, Any]) -> dict[str, Any] | None:
        vehicle_config = (config or {}).get("vehicles", {})
        configured_vehicles = vehicle_config.get("items")
        if isinstance(configured_vehicles, list) and configured_vehicles:
            ev_config = {
                "enabled": vehicle_config.get("enabled", True),
                "vehicles": [item for item in configured_vehicles if isinstance(item, dict) and item.get("ev_profile_enabled")],
            }
        else:
            ev_config = (config or {}).get("ev", {})
        if not ev_config.get("enabled", True):
            return None

        vehicles: list[dict[str, Any]] = []
        for vehicle_cfg in ev_config.get("vehicles", []):
            vehicle = self._resolve_vehicle(vehicle_cfg)
            if vehicle:
                vehicles.append(vehicle)

        if not vehicles:
            return None
        return {"enabled": True, "vehicles": vehicles}

    def _resolve_vehicle(self, vehicle_cfg: dict[str, Any]) -> dict[str, Any] | None:
        name = str(vehicle_cfg.get("label") or "E-Fahrzeug").strip()
        result: dict[str, Any] = {
            "id": str(vehicle_cfg.get("id") or name.lower().replace(" ", "_")),
            "name": name,
            "stop_charging_button_entity": str(vehicle_cfg.get("stop_charging_button_entity") or "").strip(),
        }
        has_visible_data = False

        for key in ("battery_entity", "range_entity", "charging_entity", "remaining_charge_time_entity"):
            entity_id = str(vehicle_cfg.get(key) or "").strip()
            if not entity_id:
                continue
            state = self.ha.get_state(entity_id)
            if not state:
                continue
            raw = state.get("state")
            if raw in ("unavailable", "unknown", None, ""):
                continue
            attrs = state.get("attributes", {})
            result[self._field_name(key)] = {
                "entity_id": entity_id,
                "state": raw,
                "unit": attrs.get("unit_of_measurement", ""),
                "name": attrs.get("friendly_name", entity_id),
            }
            has_visible_data = True

        if not has_visible_data:
            return None
        return result

    @staticmethod
    def _field_name(config_key: str) -> str:
        return {
            "battery_entity": "batterie",
            "range_entity": "reichweite",
            "charging_entity": "laden",
            "remaining_charge_time_entity": "verbleibende_ladezeit",
        }[config_key]
