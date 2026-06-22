"""Sync-Endpunkte — Einkaufsliste (lokal + Sync-Trigger)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.services import sync_service as svc

router = APIRouter()


@router.get("/sync/items")
def get_items() -> dict[str, Any]:
    return {"items": svc.list_items()}


@router.post("/sync/items")
def add_item(payload: dict[str, Any]) -> dict[str, Any]:
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text fehlt")
    item = svc.create_item(text)
    svc.push_item(item)
    return item


@router.patch("/sync/items/{item_id}")
def patch_item(item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    item = svc.update_item(item_id, text=payload.get("text"), checked=payload.get("checked"))
    if item is None:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    svc.push_item(item)
    return item


@router.delete("/sync/items/{item_id}")
def remove_item(item_id: str) -> dict[str, Any]:
    if not svc.delete_item(item_id):
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    svc.push_item({"id": item_id, "deleted": True})
    return {"ok": True}


@router.delete("/sync/items")
def clear_checked() -> dict[str, Any]:
    return {"deleted": svc.clear_checked()}


@router.post("/sync/trigger")
def trigger_sync() -> dict[str, Any]:
    """Manuellen Sync anstoßen — alle aktivierten Module."""
    from app.services.integration_config_service import IntegrationConfigService
    modules = (IntegrationConfigService().get_config().get("sync") or {}).get("modules", {})

    pushed = pulled = 0

    if modules.get("shopping", True):
        pushed += svc.push_unsynced()
        since   = svc.get_last_sync_time()
        pulled += svc.pull_and_merge(since)

    if modules.get("notes", False):
        svc.push_persons()
        pushed += svc.push_notes()
        pulled += svc.pull_notes()

    if modules.get("reminders", False):
        pushed += svc.push_reminders()
        pulled += svc.pull_reminders()

    if modules.get("chores", False):
        svc.push_persons()
        pushed += svc.push_chore_tasks()
        pushed += svc.push_chore_completions()
        pulled += svc.pull_chore_completions()

    return {"pushed": pushed, "pulled": pulled}
