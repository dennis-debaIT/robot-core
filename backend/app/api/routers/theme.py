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


@router.get("/display/theme/effective")
def get_effective_theme() -> dict:
    """Aktuell anzuzeigendes Theme — berücksichtigt Zeitabhängiges Design (Plus)."""
    return ThemeService().get_effective_theme()


@router.get("/display/theme/schedule")
def get_theme_schedule() -> dict:
    return ThemeService().get_schedule()


@router.post("/display/theme/schedule")
def save_theme_schedule(payload: dict) -> dict:
    return ThemeService().save_schedule(payload)
