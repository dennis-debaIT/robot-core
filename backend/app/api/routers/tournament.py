from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException

from app.services.integration_config_service import IntegrationConfigService
from app.services.tournament_service import TournamentService

router = APIRouter()


def _get_cfg() -> dict[str, Any]:
    return (IntegrationConfigService().get_config().get("tournament") or {})


@router.get("/tournament/state")
def get_tournament_state() -> dict[str, Any]:
    cfg = _get_cfg()
    if not cfg.get("enabled") or not cfg.get("api_key"):
        return {"enabled": False, "live": [], "matchday": [], "matchday_nr": None}
    svc = TournamentService(cfg["api_key"], cfg.get("competition_code", "WC"))
    data = svc.get_current()
    return {"enabled": True, **data}


@router.get("/tournament/standings")
def get_tournament_standings() -> dict:
    cfg = _get_cfg()
    if not cfg.get("enabled") or not cfg.get("api_key"):
        return {"groups": []}
    svc = TournamentService(cfg["api_key"], cfg.get("competition_code", "WC"))
    return svc.get_standings()


@router.patch("/tournament/config")
def update_tournament_config(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    allowed = {"enabled", "api_key", "competition_code"}
    patch = {k: v for k, v in payload.items() if k in allowed}
    if not patch:
        raise HTTPException(status_code=400, detail="Keine gültigen Felder")
    cfg = IntegrationConfigService()
    updated = cfg.update_config({"tournament": patch})
    TournamentService.invalidate_cache()
    return updated.get("tournament", {})
