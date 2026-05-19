from __future__ import annotations

from typing import Any

from app.services.homeassistant_service import HomeAssistantService


def _safe(val: Any, default: Any = None) -> Any:
    if val in (None, "unknown", "unavailable", ""):
        return default
    return val


def _entities_from_prefix(prefix: str) -> dict[str, str]:
    """Baut Entity-IDs aus dem Prefix (z.B. 'anycubic_kobra_s1')."""
    # Button-Prefix weicht ab (anycubic_printer statt anycubic_kobra_s1)
    btn_prefix = "anycubic_printer"
    return {
        "state":          f"sensor.{prefix}_printer_state",
        "print_state":    f"sensor.{prefix}_print_state",
        "nozzle":         f"sensor.{prefix}_nozzle_temperature",
        "nozzle_target":  f"sensor.{prefix}_target_nozzle_temperature",
        "hotbed":         f"sensor.{prefix}_hotbed_temperature",
        "hotbed_target":  f"sensor.{prefix}_target_hotbed_temperature",
        "filename":       f"sensor.{prefix}_print_filename",
        "layer":          f"sensor.{prefix}_print_layer",
        "progress":       f"sensor.{prefix}_print_progress",
        "elapsed":        f"sensor.{prefix}_print_time_elapsed",
        "remaining":      f"sensor.{prefix}_print_time_remaining",
        "snapshot":       f"image.{prefix}_anycubic_snapshot",
        "pause":          f"button.{btn_prefix}_pause_print",
        "resume":         f"button.{btn_prefix}_resume_print",
        "cancel":         f"button.{btn_prefix}_cancel_print",
    }


class PrinterService:
    PRINTING_STATES = {"printing", "preheating", "busy", "paused", "pause"}

    def __init__(self, ha: HomeAssistantService | None = None) -> None:
        self.ha = ha or HomeAssistantService()

    def get_state(self, prefix: str, entity_overrides: dict[str, str] | None = None) -> dict[str, Any]:
        ents = _entities_from_prefix(prefix)
        if entity_overrides:
            ents.update({k: v for k, v in entity_overrides.items() if v})

        result: dict[str, Any] = {"printing": False, "state": "offline"}

        def _get(key: str) -> Any:
            eid = ents.get(key, "")
            if not eid:
                return None
            s = self.ha.get_state(eid)
            return s if s else None

        def _val(key: str, default: Any = None) -> Any:
            s = _get(key)
            return _safe(s.get("state") if s else None, default) if s else default

        # Druckerstatus — "busy" deckt Aufheizen + Drucken ab
        printer_state = _val("state", "offline")
        print_state   = _val("print_state", "")
        result["state"]    = print_state or printer_state
        result["printing"] = printer_state == "busy"

        # Temperaturen
        result["nozzle_temp"]        = _val("nozzle")
        result["nozzle_temp_target"] = _val("nozzle_target")
        result["hotbed_temp"]        = _val("hotbed")
        result["hotbed_temp_target"] = _val("hotbed_target")

        # Druckdaten
        # Dateipfad-Prefix entfernen (.3mf_temp/ etc.)
        raw_fn = _val("filename") or ""
        result["filename"] = raw_fn.split("/")[-1] if "/" in raw_fn else raw_fn or None
        result["progress"]  = _val("progress")
        result["elapsed"]   = _val("elapsed")
        result["remaining"] = _val("remaining")

        # Layer "13 / 1048" → layer + total_layers
        layer_raw = _val("layer", "")
        if layer_raw and "/" in str(layer_raw):
            parts = str(layer_raw).split("/")
            try:
                result["layer"]        = int(parts[0].strip())
                result["total_layers"] = int(parts[1].strip())
            except ValueError:
                pass

        # Snapshot über robot-core Proxy (verhindert Mixed-Content auf HTTPS)
        snap = _get("snapshot")
        if snap and (snap.get("attributes") or {}).get("entity_picture"):
            result["snapshot_url"] = "/ha/printer/snapshot"

        return result

    def press_button(self, prefix: str, action: str, entity_overrides: dict[str, str] | None = None) -> bool:
        ents = _entities_from_prefix(prefix)
        if entity_overrides:
            ents.update({k: v for k, v in entity_overrides.items() if v})
        entity_id = ents.get(action, "")
        if not entity_id:
            return False
        return self.ha.call_service("button", "press", {"entity_id": entity_id})
