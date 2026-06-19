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


@router.post("/features/preview")
def set_preview(payload: dict) -> dict:
    """Setzt oder löscht den server-seitigen Edition-Preview (überschreibt Lizenz für Tests).
    {edition: 'community'|'plus'|'family'} setzt den Preview, {edition: null} löscht ihn.
    """
    edition = payload.get("edition") or None
    FeatureService().set_preview_edition(edition if isinstance(edition, str) else None)
    return FeatureService().enabled_features()
