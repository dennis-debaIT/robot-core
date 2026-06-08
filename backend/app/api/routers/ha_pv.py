from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.services.integration_config_service import IntegrationConfigService
from app.services.pv_service import PV_PROVIDERS, PvService

# Hinweis: Die kostenpflichtigen PV-Statistik-Endpunkte (/ha/pv/history,
# /ha/pv/grid-history) liegen in ha_pv_stats.py und werden in main.py
# optional registriert. Dieses Modul enthält nur die frei verfügbaren
# Endpunkte: Live-Zustand und Provider-Liste.

router = APIRouter()


@router.get("/ha/pv/providers")
def get_pv_providers() -> dict[str, Any]:
    return {
        "providers": [
            {"id": k, "label": v["label"], "sensors": v["sensors"]}
            for k, v in PV_PROVIDERS.items()
        ]
    }


@router.get("/ha/pv/state")
def get_pv_state() -> dict[str, Any]:
    config = IntegrationConfigService().get_config()
    pv_cfg = config.get("pv") or {}
    if not pv_cfg.get("enabled"):
        raise HTTPException(status_code=404, detail="PV-Modul nicht aktiv")
    sensors       = pv_cfg.get("sensors") or {}
    widget_fields = pv_cfg.get("widget_fields") or {}
    state = PvService().get_state(sensors)
    return {"state": state, "widget_fields": widget_fields}
