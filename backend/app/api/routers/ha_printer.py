from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.services.integration_config_service import IntegrationConfigService
from app.services.printer_service import PrinterService

router = APIRouter()


def _printer_cfg(config: dict) -> dict[str, Any]:
    return config.get("printer") or {}


@router.get("/ha/printer/state")
def get_printer_state() -> dict[str, Any]:
    config = IntegrationConfigService().get_config()
    cfg = _printer_cfg(config)
    if not cfg.get("enabled"):
        raise HTTPException(status_code=404, detail="Drucker-Modul nicht aktiv")
    entities = cfg.get("entities") or {}
    state = PrinterService().get_state(entities)
    return state


@router.post("/ha/printer/control/{action}")
def control_printer(action: str) -> dict[str, Any]:
    if action not in ("pause", "resume", "cancel"):
        raise HTTPException(status_code=400, detail=f"Unbekannte Aktion: {action}")
    config = IntegrationConfigService().get_config()
    cfg = _printer_cfg(config)
    if not cfg.get("enabled"):
        raise HTTPException(status_code=404, detail="Drucker-Modul nicht aktiv")
    entity_id = (cfg.get("entities") or {}).get(action, "")
    if not entity_id:
        raise HTTPException(status_code=400, detail=f"Entität für '{action}' nicht konfiguriert")
    ok = PrinterService().press_button(entity_id)
    return {"ok": ok, "action": action}
