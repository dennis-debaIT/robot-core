from __future__ import annotations

import urllib.request
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

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


@router.get("/ha/printer/snapshot")
def get_printer_snapshot() -> Response:
    """Proxyt den Drucker-Snapshot von HA (löst Mixed-Content-Problem)."""
    from app.search.providers.homeassistant import HomeAssistantProvider
    from app.services.homeassistant_runtime_config_service import HomeAssistantRuntimeConfigService
    config = IntegrationConfigService().get_config()
    cfg = _printer_cfg(config)
    prefix = cfg.get("entity_prefix", "anycubic_kobra_s1")
    ha = HomeAssistantProvider()
    snap = ha.get_state(f"image.{prefix}_anycubic_snapshot")
    if not snap:
        raise HTTPException(404, "Snapshot nicht verfügbar")
    ep = (snap.get("attributes") or {}).get("entity_picture", "")
    if not ep:
        raise HTTPException(404, "Kein entity_picture")
    ha_url = HomeAssistantRuntimeConfigService.build_base_url()
    token = HomeAssistantRuntimeConfigService.get_config().get("token", "")
    img_url = f"{ha_url}{ep}"
    try:
        req = urllib.request.Request(img_url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = resp.read()
            ct = resp.headers.get("Content-Type", "image/jpeg")
        return Response(content=data, media_type=ct, headers={"Cache-Control": "no-cache"})
    except Exception as exc:
        raise HTTPException(503, str(exc)) from exc


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
