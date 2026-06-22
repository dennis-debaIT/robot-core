"""Einkaufslisten-Endpunkte (lokal + Sync-Trigger)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.services import shopping_service as svc

router = APIRouter()


@router.get("/shopping/items")
def get_items() -> dict[str, Any]:
    return {"items": svc.list_items()}


@router.post("/shopping/items")
def add_item(payload: dict[str, Any]) -> dict[str, Any]:
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text fehlt")
    item = svc.create_item(text)
    svc.push_item(item)
    return item


@router.patch("/shopping/items/{item_id}")
def patch_item(item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    text    = payload.get("text")
    checked = payload.get("checked")
    item    = svc.update_item(item_id, text=text, checked=checked)
    if item is None:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    svc.push_item(item)
    return item


@router.delete("/shopping/items/{item_id}")
def remove_item(item_id: str) -> dict[str, Any]:
    if not svc.delete_item(item_id):
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    svc.push_item({"id": item_id, "deleted": True})
    return {"ok": True}


@router.delete("/shopping/items")
def clear_checked() -> dict[str, Any]:
    count = svc.clear_checked()
    return {"deleted": count}


@router.post("/shopping/sync")
def trigger_sync() -> dict[str, Any]:
    """Manuellen Sync anstoßen (Push unsynced + Pull neue)."""
    pushed = svc.push_unsynced()
    since  = svc.get_last_sync_time()
    pulled = svc.pull_and_merge(since)
    return {"pushed": pushed, "pulled": pulled}
