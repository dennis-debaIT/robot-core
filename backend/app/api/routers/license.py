from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from app.services.feature_service import FeatureService
from app.services.license_service import LicenseService, _LICENSE_FILE

router = APIRouter()


@router.get("/license/status")
def license_status() -> dict:
    return LicenseService().status()


@router.post("/license")
def install_license(payload: dict) -> dict:
    """Signierte license.json hochladen. Bei Gültigkeit wird sie gespeichert
    und die Edition (DB + Build-Datei) entsprechend gesetzt."""
    result = LicenseService().install(payload)
    if result.get("valid"):
        FeatureService().set_edition(result.get("plan", "community"))
    return result


@router.delete("/license")
def remove_license() -> dict:
    """Lizenz entfernen → zurück auf Community."""
    try:
        Path(_LICENSE_FILE).unlink(missing_ok=True)
    except OSError:
        pass
    FeatureService().set_edition("community")
    return {"removed": True, "plan": "community"}
