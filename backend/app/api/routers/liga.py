from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

from app.services.integration_config_service import IntegrationConfigService
from app.services.liga_service import LigaService

router = APIRouter()

_ALLOWED_CODES = {"BL1", "BL2", "BL3"}


def _get_cfg() -> dict[str, Any]:
    return (IntegrationConfigService().get_config().get("liga") or {})


@router.get("/liga/state")
def get_liga_state() -> dict[str, Any]:
    cfg = _get_cfg()
    if not cfg.get("enabled") or not cfg.get("api_key"):
        return {"enabled": False, "leagues": []}
    codes = [c for c in (cfg.get("leagues") or []) if c in _ALLOWED_CODES]
    if not codes:
        return {"enabled": True, "leagues": []}
    svc = LigaService(cfg["api_key"])
    leagues = svc.get_state(codes)
    result: dict[str, Any] = {"enabled": True, "leagues": leagues}
    team_id = cfg.get("favorite_team_id")
    if team_id:
        result["team_focus"]          = svc.get_team_focus(int(team_id))
        result["favorite_team_id"]    = team_id
        result["favorite_team_name"]  = cfg.get("favorite_team_name", "")
    return result


@router.get("/liga/standings")
def get_liga_standings(code: str = Query(...)) -> dict[str, Any]:
    if code not in _ALLOWED_CODES:
        raise HTTPException(400, f"Unbekannte Liga: {code}")
    cfg = _get_cfg()
    if not cfg.get("enabled") or not cfg.get("api_key"):
        return {"code": code, "table": []}
    return LigaService(cfg["api_key"]).get_standings(code)


@router.get("/liga/teams")
def get_liga_teams() -> dict[str, Any]:
    from app.services.openligadb_liga import get_teams as _oldb_get_teams
    cfg = _get_cfg()
    api_key = cfg.get("api_key")
    if api_key:
        # football-data.org als Primärquelle (BL1), OpenLigaDB-Fallback für BL2/BL3
        return {"teams": LigaService(api_key).get_teams(sorted(_ALLOWED_CODES))}
    # Kein API-Key: direkt OpenLigaDB für alle drei Ligen (Lieblingsverein-Picker)
    teams: list[dict[str, Any]] = []
    for code in sorted(_ALLOWED_CODES):
        teams.extend(_oldb_get_teams(code))
    teams.sort(key=lambda t: (t.get("league_code", ""), t.get("name", "")))
    return {"teams": teams}


@router.patch("/liga/config")
def update_liga_config(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    allowed = {"enabled", "api_key", "leagues", "favorite_team_id", "favorite_team_name"}
    patch = {k: v for k, v in payload.items() if k in allowed}
    if not patch:
        raise HTTPException(400, "Keine gültigen Felder")
    cfg_svc = IntegrationConfigService()
    updated = cfg_svc.update_config({"liga": patch})
    LigaService.invalidate_cache()
    return updated.get("liga", {})
