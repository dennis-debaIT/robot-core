from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.services.robot_service import RobotService


router = APIRouter()


@router.get("/ha/robots")
def get_ha_robots() -> dict[str, Any]:
    from app.services.integration_config_service import IntegrationConfigService

    return {"robots": RobotService().list_robots_with_config(IntegrationConfigService().get_config())}


@router.get("/ha/robots/{entity_id}/errors")
def robot_error_log(entity_id: str) -> dict[str, Any]:
    from app.services.integration_config_service import IntegrationConfigService

    return {"entries": RobotService().get_error_log(entity_id, IntegrationConfigService().get_config())}


@router.post("/ha/robots/{entity_id}/command")
def robot_command(entity_id: str, body: dict[str, Any]) -> dict[str, Any]:
    try:
        return RobotService().command(entity_id, body.get("command", ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/ha/dreame/clean_segments")
def dreame_clean_segments(body: dict[str, Any]) -> dict[str, Any]:
    try:
        return RobotService().clean_segments(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/ha/robots/{robot_name}/sensors")
def get_robot_sensors(robot_name: str) -> dict[str, Any]:
    return RobotService().get_robot_sensors(robot_name)


@router.get("/ha/robots/{entity_id}/detect-config")
def detect_vacuum_config(entity_id: str) -> dict[str, Any]:
    """Erkennt Vacuum-Konfiguration automatisch aus HA-Entities (Räume, Kamera, Modi)."""
    return RobotService().detect_vacuum_config(entity_id)
