from __future__ import annotations

from fastapi import APIRouter

from app.services.layout_service import LayoutService

router = APIRouter()


@router.get("/display/layout")
def get_layout() -> dict:
    return LayoutService().get_layout()


@router.post("/display/layout")
def save_layout(payload: dict) -> dict:
    return LayoutService().save_layout(payload)


@router.post("/display/layout/reset")
def reset_layout() -> dict:
    return LayoutService().reset_layout()
