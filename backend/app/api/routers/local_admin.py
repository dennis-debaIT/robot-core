from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.api.deps import LOCAL_ADMIN_CSS, LOCAL_ADMIN_INDEX
from app.services.integration_config_service import IntegrationConfigService
from app.services.homeassistant_runtime_config_service import HomeAssistantRuntimeConfigService


router = APIRouter()


@router.get("/local-admin", response_class=FileResponse)
def local_admin_page() -> Any:
    return FileResponse(LOCAL_ADMIN_INDEX)


@router.get("/local-admin.css", response_class=FileResponse)
def local_admin_css() -> Any:
    return FileResponse(LOCAL_ADMIN_CSS, media_type="text/css")


@router.get("/local-admin/integrations/catalog")
def get_local_admin_catalog() -> dict[str, Any]:
    service = IntegrationConfigService()
    return {
        "catalog": service.get_catalog(),
        "config": service.get_config(),
    }


@router.get("/local-admin/integrations/config")
def get_local_admin_config() -> dict[str, Any]:
    return {"config": IntegrationConfigService().get_config()}


@router.patch("/local-admin/integrations/config")
def patch_local_admin_config(payload: dict[str, Any]) -> dict[str, Any]:
    service = IntegrationConfigService()
    updated = service.update_config(payload)
    return {"config": updated}


@router.post("/local-admin/system/home-assistant/test")
def test_home_assistant_connection(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    config = payload.get("home_assistant") if payload else None
    result = HomeAssistantRuntimeConfigService.test_connection(config)
    return {"result": result}
