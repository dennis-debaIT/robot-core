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


@router.get("/tournament/debug")
def get_tournament_debug() -> dict[str, Any]:
    """Gibt die rohen Spieldaten von football-data.org zurück (stage, matchday, status)."""
    from urllib.request import Request
    from urllib.error import HTTPError, URLError
    import ssl as _ssl
    cfg = _get_cfg()
    if not cfg.get("enabled") or not cfg.get("api_key"):
        return {"error": "nicht konfiguriert", "api_key_set": bool(cfg.get("api_key")), "enabled": cfg.get("enabled")}
    api_key = cfg["api_key"]
    code    = cfg.get("competition_code", "WC")
    url     = f"https://api.football-data.org/v4/competitions/{code}/matches"
    ctx = _ssl.create_default_context()
    try:
        req = Request(url, headers={"X-Auth-Token": api_key})
        import urllib.request as _ur
        with _ur.urlopen(req, timeout=10, context=ctx) as resp:
            import json as _json
            raw = _json.loads(resp.read().decode())
        matches = raw.get("matches", [])
        summary: dict[str, Any] = {}
        for m in matches:
            stage  = m.get("stage") or "None"
            mday   = m.get("matchday")
            status = m.get("status", "?")
            key    = f"{stage}|md={mday}"
            if key not in summary:
                summary[key] = {"stage": stage, "matchday": mday, "statuses": {}}
            summary[key]["statuses"][status] = summary[key]["statuses"].get(status, 0) + 1
        return {"total": len(matches), "stages": list(summary.values()),
                "competition": raw.get("competition", {}).get("name"), "season": raw.get("filters")}
    except HTTPError as e:
        import json as _json
        body = ""
        try:
            body = e.read().decode()
        except Exception:
            pass
        return {"error": f"HTTP {e.code}", "url": url, "body": body}
    except URLError as e:
        return {"error": f"URLError: {e.reason}", "url": url}
    except Exception as e:
        return {"error": str(e), "url": url}


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
