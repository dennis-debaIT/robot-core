from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.services.ev_service import EvService
from app.services.fuel_service import FuelService
from app.services.integration_config_service import IntegrationConfigService
from app.services.vehicle_service import VehicleService


router = APIRouter()


@router.get("/ev")
def get_ev_status() -> dict[str, Any]:
    result = EvService().display_data(IntegrationConfigService().get_config())
    if not result:
        raise HTTPException(status_code=503, detail="EV-Daten nicht verfügbar")
    return result


@router.get("/fuel")
def get_fuel_prices() -> dict[str, Any]:
    result = FuelService().get_display_data(IntegrationConfigService().get_config())
    if not result:
        raise HTTPException(status_code=503, detail="Kraftstoffpreise nicht verfügbar")
    return result


@router.get("/vehicles")
def get_vehicles() -> dict[str, Any]:
    return VehicleService().list_vehicles(IntegrationConfigService().get_config())


@router.get("/vehicles/{vehicle_id}/location-history")
def get_vehicle_location_history(vehicle_id: str, days: int = 14) -> dict[str, Any]:
    return VehicleService().location_history(vehicle_id, days)


@router.get("/vehicles/{vehicle_id}/location-history/addresses")
def get_vehicle_location_addresses(vehicle_id: str, days: int = 14) -> dict:
    return VehicleService().location_history_clustered(vehicle_id, days)


@router.get("/vehicles/{vehicle_id}/charging-history")
def get_vehicle_charging_history(vehicle_id: str, period: str = "7days") -> dict[str, Any]:
    config = IntegrationConfigService().get_config()
    svc = VehicleService()
    # battery_entity aus Config ermitteln
    battery_entity = ""
    for item in (config.get("vehicles") or {}).get("items") or []:
        if str(item.get("id") or "") == vehicle_id:
            battery_entity = str(item.get("battery_entity") or "").strip()
            break
    return svc.charging_history(vehicle_id, period, battery_entity)


@router.post("/vehicles/location-history/poll")
def poll_vehicle_location_history() -> dict[str, Any]:
    return VehicleService().record_locations(IntegrationConfigService().get_config())


@router.get("/ha/doorbell")
def get_doorbell_sensors() -> dict[str, Any]:
    from app.search.providers.homeassistant import HomeAssistantProvider

    return {"doorbells": HomeAssistantProvider().get_doorbell_sensors()}
