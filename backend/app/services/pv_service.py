from __future__ import annotations

from typing import Any

from app.services.homeassistant_service import HomeAssistantService

PV_PROVIDERS: dict[str, dict[str, Any]] = {
    "solarman": {
        "label": "Solarman",
        "sensors": {
            "power":       "sensor.solarman_total_ac_output_power_active",
            "daily":       "sensor.solarman_daily_production",
            "temperature": "sensor.solarman_radiator_temperature",
            "last_update": "sensor.solarman_status_lastupdate",
        },
    },
    "fronius": {
        "label": "Fronius Solar.web",
        "sensors": {
            "power":       "",
            "daily":       "",
            "temperature": "",
            "last_update": "",
        },
    },
    "sma": {
        "label": "SMA",
        "sensors": {
            "power":       "",
            "daily":       "",
            "temperature": "",
            "last_update": "",
        },
    },
    "enphase": {
        "label": "Enphase",
        "sensors": {
            "power":       "",
            "daily":       "",
            "temperature": "",
            "last_update": "",
        },
    },
    "custom": {
        "label": "Benutzerdefiniert",
        "sensors": {
            "power":       "",
            "daily":       "",
            "temperature": "",
            "last_update": "",
        },
    },
}


class PvService:
    def __init__(self, ha: HomeAssistantService | None = None) -> None:
        self.ha = ha or HomeAssistantService()

    def get_state(self, sensors: dict[str, str]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, entity_id in sensors.items():
            if not entity_id:
                continue
            state = self.ha.get_state(entity_id)
            if state:
                result[key] = {
                    "value": state.get("state"),
                    "unit":  (state.get("attributes") or {}).get("unit_of_measurement", ""),
                    "entity_id": entity_id,
                }
        return result
