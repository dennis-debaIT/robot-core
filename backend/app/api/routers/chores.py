"""Hausaufgaben-Endpunkte — Erika Plus (kostenpflichtig).

Komplettes Modul (Aufgabenverwaltung, Erledigungs-Log, Statistiken). Wird in
main.py *optional* importiert — fehlt die Datei (Community-Build), existieren
die Endpunkte schlicht nicht (404), statt eine Berechtigungsmeldung zu liefern.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.services.chore_service import ChoreService
from app.services.integration_config_service import IntegrationConfigService

router = APIRouter()


@router.get("/chores/tasks")
def list_chore_tasks() -> dict[str, Any]:
    config = IntegrationConfigService().get_config()
    overall_winner_enabled = bool((config.get("chores") or {}).get("overall_winner_enabled", True))
    return {
        "tasks": ChoreService().list_tasks(),
        "overall_winner_enabled": overall_winner_enabled,
    }


@router.post("/chores/tasks")
def create_chore_task(payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name fehlt")
    icon = str(payload.get("icon") or "").strip() or None
    return ChoreService().create_task(name, icon)


@router.patch("/chores/tasks/{task_id}")
def update_chore_task(task_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    name = payload.get("name")
    if name is not None:
        name = str(name).strip()
        if not name:
            raise HTTPException(status_code=400, detail="Name fehlt")
    icon = payload.get("icon")
    if icon is not None:
        icon = str(icon).strip() or None
    sort_order = payload.get("sort_order")
    active = payload.get("active")
    result = ChoreService().update_task(
        task_id,
        name=name,
        icon=icon,
        sort_order=sort_order,
        active=active,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")
    return result


@router.delete("/chores/tasks/{task_id}")
def delete_chore_task(task_id: int) -> dict[str, Any]:
    if not ChoreService().delete_task(task_id):
        raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")
    return {"ok": True}


@router.post("/chores/completions")
def log_chore_completion(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        task_id = int(payload.get("task_id"))
        person_id = int(payload.get("person_id"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="task_id/person_id fehlen")
    return ChoreService().log_completion(task_id, person_id)


@router.delete("/chores/completions/{completion_id}")
def delete_chore_completion(completion_id: int) -> dict[str, Any]:
    if not ChoreService().delete_completion(completion_id):
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    return {"ok": True}


@router.get("/chores/tasks/{task_id}/completions")
def get_chore_completions(task_id: int, period: str = "week", person_id: int | None = None) -> dict[str, Any]:
    if period not in ("week", "month", "year"):
        period = "week"
    return {"completions": ChoreService().list_completions(task_id, period=period, person_id=person_id)}


@router.get("/chores/tasks/{task_id}/stats")
def get_chore_task_stats(task_id: int, period: str = "week") -> dict[str, Any]:
    if period not in ("week", "month", "year"):
        period = "week"
    result = ChoreService().task_stats(task_id, period)
    if result is None:
        raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")
    return result


@router.get("/chores/overall-stats")
def get_chore_overall_stats() -> dict[str, Any]:
    return ChoreService().overall_weekly_stats()
