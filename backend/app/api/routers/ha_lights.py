from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.services.integration_config_service import IntegrationConfigService
from app.services.light_service import LightService


router = APIRouter()


@router.get("/ha/lights")
def get_ha_lights() -> dict[str, Any]:
    config = IntegrationConfigService().get_config()
    return {"lights": LightService().list_lights(config)}


@router.post("/ha/lights/control")
def control_ha_light(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return LightService().control_light(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/ha/select/{entity_id}/set")
def set_select_option(entity_id: str, body: dict[str, Any]) -> dict[str, Any]:
    return LightService().set_select_option(entity_id, body.get("option", ""))


@router.post("/ha/button/{entity_id}/press")
def press_button(entity_id: str) -> dict[str, Any]:
    return LightService().press_button(entity_id)


@router.get("/ha/entity/{entity_id:path}/state")
def get_entity_state(entity_id: str) -> dict[str, Any]:
    state = LightService().get_entity_state(entity_id)
    if not state:
        raise HTTPException(status_code=404, detail=entity_id)
    return state
