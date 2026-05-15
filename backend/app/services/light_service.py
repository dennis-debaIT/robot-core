from __future__ import annotations

from typing import Any

from app.services.homeassistant_service import HomeAssistantService


class LightService:
    def __init__(self, ha: HomeAssistantService | None = None) -> None:
        self.ha = ha or HomeAssistantService()

    def list_lights(self, config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        lights = self.ha.get_lights()
        if config is None:
            return lights

        light_config = (config or {}).get("lights") or {}
        if not light_config.get("enabled", True):
            return []

        selected = [str(item) for item in light_config.get("selected_entities") or [] if str(item)]
        if not selected:
            selected = [item["entity_id"] for item in lights if str(item.get("entity_id", "")).startswith("light.")]

        selected_set = set(selected)
        member_set: set[str] = set()
        for item in lights:
            if item.get("entity_id") in selected_set:
                member_set.update(str(member) for member in item.get("members") or [])

        allowed = selected_set | member_set
        return [item for item in lights if item.get("entity_id") in allowed]

    def control_light(self, payload: dict[str, Any]) -> dict[str, Any]:
        entity_id = payload.get("entity_id", "")
        service = payload.get("service", "toggle")
        domain = entity_id.split(".")[0] if "." in entity_id else "light"
        if domain not in ("light", "switch"):
            raise ValueError("Invalid entity domain")
        if service not in ("turn_on", "turn_off", "toggle"):
            raise ValueError("Invalid service")

        data: dict[str, Any] = {"entity_id": entity_id}
        if domain == "light":
            if payload.get("brightness_pct") is not None:
                data["brightness_pct"] = int(payload["brightness_pct"])
            if payload.get("rgb_color") is not None:
                data["rgb_color"] = payload["rgb_color"]
            if payload.get("color_temp") is not None:
                data["color_temp"] = int(payload["color_temp"])

        ok = self.ha.call_service(domain, service, data)
        return {"success": ok, "entity_id": entity_id, "service": service}

    def set_select_option(self, entity_id: str, option: str) -> dict[str, Any]:
        ok = self.ha.call_service(
            "select",
            "select_option",
            {"entity_id": entity_id, "option": option},
        )
        return {"ok": ok, "entity_id": entity_id, "option": option}

    def press_button(self, entity_id: str) -> dict[str, Any]:
        ok = self.ha.call_service("button", "press", {"entity_id": entity_id})
        return {"ok": ok, "entity_id": entity_id}

    def get_entity_state(self, entity_id: str) -> dict[str, Any] | None:
        state = self.ha.get_state(entity_id)
        if not state:
            return None
        attrs = state.get("attributes", {})
        return {
            "state": state.get("state", ""),
            "unit": attrs.get("unit_of_measurement", ""),
            "name": attrs.get("friendly_name", entity_id),
        }
