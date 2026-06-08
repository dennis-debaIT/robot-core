from __future__ import annotations

from fastapi import APIRouter

from app.services.feature_service import FeatureService

router = APIRouter()


@router.get("/features")
def get_features() -> dict:
    return FeatureService().enabled_features()


@router.post("/features/edition")
def set_edition(payload: dict) -> dict:
    FeatureService().set_edition(str(payload.get("edition") or ""))
    return FeatureService().enabled_features()
