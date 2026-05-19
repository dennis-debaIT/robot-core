from __future__ import annotations

from typing import Any

from app.services.homeassistant_service import HomeAssistantService


def _safe(val: Any, default: Any = None) -> Any:
    if val in (None, "unknown", "unavailable", ""):
        return default
    return val


class PrinterService:
    def __init__(self, ha: HomeAssistantService | None = None) -> None:
        self.ha = ha or HomeAssistantService()

    def get_state(self, entities: dict[str, str]) -> dict[str, Any]:
        result: dict[str, Any] = {"printing": False}

        # Printer state
        state_id = entities.get("state", "")
        if state_id:
            s = self.ha.get_state(state_id)
            if s:
                state_val = _safe(s.get("state"), "offline")
                result["state"] = state_val
                result["printing"] = state_val in ("printing", "busy")
                attrs = s.get("attributes") or {}
                # Some bridges embed print_job in state attributes
                for key in ("filename", "layer", "total_layers", "progress",
                            "elapsed_time", "remaining_time", "print_state"):
                    if key in attrs:
                        result[key] = _safe(attrs[key])

        # Temperatures
        nozzle_id = entities.get("nozzle", "")
        if nozzle_id:
            s = self.ha.get_state(nozzle_id)
            if s:
                attrs = s.get("attributes") or {}
                result["nozzle_temp"]        = _safe(s.get("state"))
                result["nozzle_temp_target"] = _safe(attrs.get("target_temperature") or attrs.get("nozzle_target"))
                result["nozzle_unit"]        = attrs.get("unit_of_measurement", "°C")

        hotbed_id = entities.get("hotbed", "")
        if hotbed_id:
            s = self.ha.get_state(hotbed_id)
            if s:
                attrs = s.get("attributes") or {}
                result["hotbed_temp"]        = _safe(s.get("state"))
                result["hotbed_temp_target"] = _safe(attrs.get("target_temperature") or attrs.get("hotbed_target"))
                result["hotbed_unit"]        = attrs.get("unit_of_measurement", "°C")

        # Print job (if separate entity)
        job_id = entities.get("print_job", "")
        if job_id and job_id != entities.get("state", ""):
            s = self.ha.get_state(job_id)
            if s:
                attrs = s.get("attributes") or {}
                for key, attr_key in [
                    ("filename",       "filename"),
                    ("layer",          "layer"),
                    ("total_layers",   "total_layers"),
                    ("progress",       "progress"),
                    ("elapsed_time",   "elapsed_time"),
                    ("remaining_time", "remaining_time"),
                ]:
                    v = _safe(attrs.get(attr_key) or s.get("state") if attr_key == "progress" else attrs.get(attr_key))
                    if v is not None:
                        result[key] = v

        # Snapshot URL
        snap_id = entities.get("snapshot", "")
        if snap_id:
            s = self.ha.get_state(snap_id)
            if s:
                attrs = s.get("attributes") or {}
                result["snapshot_url"] = attrs.get("entity_picture") or attrs.get("url") or ""

        return result

    def press_button(self, entity_id: str) -> bool:
        return self.ha.call_service("button", "press", {"entity_id": entity_id})
