from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from app.services.integration_config_service import IntegrationConfigService
from app.services.tournament_service import _MAX_MATCH_MINUTES, TournamentService

router = APIRouter()

# Wie lange nach dem Finale bleibt das Turnier-Overlay noch sichtbar, bevor
# automatisch auf "kein aktives Turnier" umgeschaltet wird.
_POST_FINAL_HIDE_HOURS = 24
# Wie viele Tage vor dem konfigurierten Start des NÄCHSTEN Turniers wird
# automatisch darauf umgeschaltet (sobald dessen Spielplan echte Daten liefert).
_PRE_START_SHOW_DAYS = 14


def _get_cfg() -> dict[str, Any]:
    return (IntegrationConfigService().get_config().get("tournament") or {})


def _final_concluded_since(data: dict[str, Any]) -> datetime | None:
    """None wenn das Turnier noch läuft (oder der Endstand noch nicht sicher
    ermittelbar ist). Sonst: Zeitpunkt an dem das Finale sicher vorbei war
    (letzter Anstoß + Spieldauer-Puffer)."""
    if data.get("stage") != "FINAL":
        return None
    final_matches = data.get("matchday") or []
    if not final_matches or any(m.get("status") != "FINISHED" for m in final_matches):
        return None
    dates = [m.get("utcDate") for m in final_matches if m.get("utcDate")]
    if not dates:
        return None
    try:
        kickoffs = [datetime.fromisoformat(d.replace("Z", "+00:00")) for d in dates]
    except ValueError:
        return None
    return max(kickoffs) + timedelta(minutes=_MAX_MATCH_MINUTES)


def _effective_competition(cfg: dict[str, Any]) -> tuple[str, bool]:
    """Ermittelt welcher competition_code gerade angezeigt werden soll und ob
    das Turnier-Overlay überhaupt sichtbar sein soll (Gnadenfrist nach dem
    Finale, danach automatischer Wechsel auf das nächste konfigurierte
    Turnier sobald dessen Zeitfenster beginnt UND es echte Spieldaten hat)."""
    configured_code = cfg.get("competition_code", "WC")
    data = TournamentService(cfg["api_key"], configured_code).get_current()
    now = datetime.now(timezone.utc)

    concluded_since = _final_concluded_since(data)
    if concluded_since is None:
        return configured_code, True  # Turnier läuft noch — normaler Betrieb
    if now < concluded_since + timedelta(hours=_POST_FINAL_HIDE_HOURS):
        return configured_code, True  # Gnadenfrist nach dem Finale

    next_code = cfg.get("next_competition_code")
    next_start = cfg.get("next_start_date")
    if next_code and next_start:
        try:
            start_dt = datetime.fromisoformat(next_start).replace(tzinfo=timezone.utc)
        except ValueError:
            start_dt = None
        if start_dt and now >= start_dt - timedelta(days=_PRE_START_SHOW_DAYS):
            next_data = TournamentService(cfg["api_key"], next_code).get_current()
            if next_data.get("matchday"):
                return next_code, True

    return configured_code, False


@router.get("/tournament/state")
def get_tournament_state() -> dict[str, Any]:
    cfg = _get_cfg()
    if not cfg.get("enabled") or not cfg.get("api_key"):
        return {"enabled": False, "live": [], "matchday": [], "matchday_nr": None}
    code, visible = _effective_competition(cfg)
    if not visible:
        return {"enabled": False, "live": [], "matchday": [], "matchday_nr": None}
    data = TournamentService(cfg["api_key"], code).get_current()
    return {"enabled": True, **data}


@router.get("/tournament/standings")
def get_tournament_standings() -> dict:
    cfg = _get_cfg()
    if not cfg.get("enabled") or not cfg.get("api_key"):
        return {"groups": []}
    code, visible = _effective_competition(cfg)
    if not visible:
        return {"groups": []}
    return TournamentService(cfg["api_key"], code).get_standings()


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
    allowed = {"enabled", "api_key", "competition_code", "next_competition_code", "next_start_date"}
    patch = {k: v for k, v in payload.items() if k in allowed}
    if not patch:
        raise HTTPException(status_code=400, detail="Keine gültigen Felder")
    cfg = IntegrationConfigService()
    updated = cfg.update_config({"tournament": patch})
    TournamentService.invalidate_cache()
    return updated.get("tournament", {})
