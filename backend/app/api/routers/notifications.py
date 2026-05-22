from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.services.notification_service import NotificationService

router = APIRouter()


@router.get("/notifications")
def list_notifications(unread_only: bool = False) -> dict[str, Any]:
    return {"notifications": NotificationService().list_notifications(unread_only)}


@router.get("/notifications/count")
def notification_count() -> dict[str, Any]:
    return {"unread": NotificationService().unread_count()}


@router.post("/notifications/{notification_id}/read")
def mark_read(notification_id: int) -> dict[str, Any]:
    NotificationService().mark_read(notification_id)
    return {"ok": True}


@router.post("/notifications/read-all")
def mark_all_read() -> dict[str, Any]:
    NotificationService().mark_all_read()
    return {"ok": True}


@router.delete("/notifications")
def delete_all_notifications() -> dict[str, Any]:
    NotificationService().delete_all()
    return {"ok": True}


@router.delete("/notifications/{notification_id}")
def delete_notification(notification_id: int) -> dict[str, Any]:
    NotificationService().delete_notification(notification_id)
    return {"ok": True}


@router.get("/notification-rules")
def list_rules() -> dict[str, Any]:
    return {"rules": NotificationService().list_rules()}


@router.post("/notification-rules")
def create_rule(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return NotificationService().create_rule(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/notification-rules/{rule_id}")
def update_rule(rule_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    NotificationService().update_rule(rule_id, payload)
    return {"ok": True}


@router.delete("/notification-rules/{rule_id}")
def delete_rule(rule_id: int) -> dict[str, Any]:
    NotificationService().delete_rule(rule_id)
    return {"ok": True}
