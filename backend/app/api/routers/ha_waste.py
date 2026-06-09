from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.services.integration_config_service import IntegrationConfigService
from app.services.waste_service import WasteService

router = APIRouter()


@router.get("/ha/waste")
def get_waste() -> dict[str, Any]:
    config = IntegrationConfigService().get_config()
    return WasteService().get_display_data(config)
