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
    prefix = cfg.get("entity_prefix", "anycubic_kobra_s1")
    overrides = cfg.get("entity_overrides") or {}
    return PrinterService().get_state(prefix, overrides)


@router.post("/ha/printer/control/{action}")
def control_printer(action: str) -> dict[str, Any]:
    if action not in ("pause", "resume", "cancel"):
        raise HTTPException(status_code=400, detail=f"Unbekannte Aktion: {action}")
    config = IntegrationConfigService().get_config()
    cfg = _printer_cfg(config)
    if not cfg.get("enabled"):
        raise HTTPException(status_code=404, detail="Drucker-Modul nicht aktiv")
    prefix = cfg.get("entity_prefix", "anycubic_kobra_s1")
    overrides = cfg.get("entity_overrides") or {}
    ok = PrinterService().press_button(prefix, action, overrides)
    return {"ok": ok, "action": action}
