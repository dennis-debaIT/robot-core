from __future__ import annotations

from fastapi import APIRouter

from app.services.theme_service import ThemeService

router = APIRouter()


@router.get("/display/theme")
def get_theme() -> dict:
    return ThemeService().get_theme()


@router.post("/display/theme")
def save_theme(payload: dict) -> dict:
    return ThemeService().save_theme(payload)


@router.post("/display/theme/reset")
def reset_theme() -> dict:
    return ThemeService().reset_theme()
