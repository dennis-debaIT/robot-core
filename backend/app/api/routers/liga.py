from __future__ import annotations

import hashlib
import json
import pathlib
import urllib.parse
import urllib.request
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import Response

from app.services.integration_config_service import IntegrationConfigService
from app.services.liga_service import LigaService

router = APIRouter()

_ALLOWED_CODES = {"BL1", "BL2", "BL3"}


def _require_liga_plus() -> None:
    """Marktwerte, Spielerprofile, Kader-Browsing anderer Vereine, letzte Spiele
    fremder Teams — die eigentliche Tabelle/Live-Spieltag/eigener Favorit bleibt frei."""
    from app.services.feature_service import FeatureService
    if not FeatureService().has_feature("liga_plus"):
        raise HTTPException(status_code=403, detail="Diese Liga-Ansicht erfordert Erika Plus")

# ── Disk-Cache für TM-Bilder ───────────────────────────────────────────────────
_IMG_CACHE_DIR = pathlib.Path("/data/tm_cache/img")


def _get_cfg() -> dict[str, Any]:
    return (IntegrationConfigService().get_config().get("liga") or {})


def _get_api_key(cfg: dict[str, Any]) -> str:
    """football-data.org nutzt einen einzigen Account-Key für alle Wettbewerbe
    (Bundesliga wie WM/EM) — die Admin-UI lässt ihn aber getrennt fürs Liga- und
    fürs Turnier-Modul eintragen. Fällt auf den Turnier-Key zurück, wenn im
    Liga-Modul keiner hinterlegt ist (z.B. Haushalt nutzt nur WM/EM und hat das
    Liga-Modul nie eingerichtet) — sonst schlägt Kader-Browsing für National-
    mannschaften aus der Turnier-Ansicht heraus mangels Key fehl."""
    key = cfg.get("api_key")
    if key:
        return key
    tournament_cfg = IntegrationConfigService().get_config().get("tournament") or {}
    return tournament_cfg.get("api_key") or ""


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
        return {"teams": LigaService(api_key).get_teams(sorted(_ALLOWED_CODES))}
    teams: list[dict[str, Any]] = []
    for code in sorted(_ALLOWED_CODES):
        teams.extend(_oldb_get_teams(code))
    teams.sort(key=lambda t: (t.get("league_code", ""), t.get("name", "")))
    return {"teams": teams}


@router.get("/liga/tm/profile")
def get_tm_profile(team_name: str = Query("")) -> dict[str, Any]:
    _require_liga_plus()
    from app.services.transfermarkt_service import TransfermarktService
    if not team_name.strip():
        raise HTTPException(400, "team_name fehlt")
    profile = TransfermarktService().get_club_profile(team_name.strip())
    if not profile:
        raise HTTPException(404, "Verein nicht auf Transfermarkt gefunden")
    return profile


@router.get("/liga/tm/players")
def get_tm_players(team_name: str = Query("")) -> dict[str, Any]:
    _require_liga_plus()
    from app.services.transfermarkt_service import TransfermarktService
    if not team_name.strip():
        raise HTTPException(400, "team_name fehlt")
    players = TransfermarktService().get_club_players(team_name.strip())
    if players is None:
        raise HTTPException(404, "Verein nicht auf Transfermarkt gefunden")
    return {"players": players or []}


@router.get("/liga/person/{person_id}")
def get_person_profile(person_id: int) -> dict[str, Any]:
    """Erweitertes Spielerprofil via football-data.org /v4/persons/{id} — aktueller Verein + Vertrag."""
    _require_liga_plus()
    cfg = _get_cfg()
    api_key = _get_api_key(cfg)
    if not api_key:
        raise HTTPException(400, "Liga nicht konfiguriert")
    data = LigaService(api_key).get_person_profile(person_id)
    if not data:
        raise HTTPException(404, "Spielerprofil nicht verfügbar")
    return data


@router.get("/liga/tm/club-transfers")
def get_club_transfers(team_name: str = Query("")) -> dict[str, Any]:
    """Zugänge + Abgänge der laufenden Saison mit echten Ablösesummen."""
    _require_liga_plus()
    from app.services.transfermarkt_service import TransfermarktService
    if not team_name.strip():
        raise HTTPException(400, "team_name fehlt")
    result = TransfermarktService().get_club_transfers(team_name.strip())
    if result is None:
        raise HTTPException(404, "Verein nicht gefunden")
    return result


@router.get("/liga/tm/player-search")
def search_tm_player(name: str = Query("")) -> dict[str, Any]:
    """Spieler per Name auf TM suchen — liefert tm_id, marketValue, club, position, age, nationalities."""
    _require_liga_plus()
    from app.services.transfermarkt_service import TransfermarktService
    if not name.strip():
        raise HTTPException(400, "name fehlt")
    result = TransfermarktService().search_player(name.strip())
    if not result:
        raise HTTPException(404, "Spieler nicht gefunden")
    return result


@router.get("/liga/tm/player/{player_id}")
def get_tm_player_profile(player_id: str) -> dict[str, Any]:
    """Einzelnes Spieler-Profil — 30-Tage-Disk-Cache, lazy auf Profilaufruf."""
    _require_liga_plus()
    from app.services.transfermarkt_service import TransfermarktService
    profile = TransfermarktService().get_player_profile(player_id)
    if not profile:
        raise HTTPException(404, "Spielerprofil nicht verfügbar")
    return profile


@router.get("/liga/kader-full")
def get_full_kader(team_id: int = Query(0), team_name: str = Query("")) -> dict[str, Any]:
    """Sofortige Kader-Rückgabe (Disk-Cache oder schnelle fd.o+TM-Liste).

    Stale-while-revalidate: vorhandener Cache wird immer sofort serviert.
    Vollständige TM-Profil-Anreicherung läuft im Daemon-Thread im Hintergrund
    und schreibt das Ergebnis persistent auf Disk (7-Tage-Stale-Schwelle).
    """
    _require_liga_plus()
    if not team_name.strip():
        raise HTTPException(400, "team_name fehlt")
    cfg = _get_cfg()
    svc = LigaService(_get_api_key(cfg))
    return svc.get_full_kader(team_id or None, team_name.strip())


@router.get("/liga/team-detail")
def get_team_detail(team_id: int = Query(...)) -> dict[str, Any]:
    """Team-Fokus (letzte 5 Spiele + nächstes Spiel) für beliebigen Verein.

    Für den eigenen Favoriten-Verein bleibt das frei — /liga/state liefert
    dieselben Daten (team_focus) für ihn bereits ungegated; nur das Anschauen
    FREMDER Vereine ("Vereinsseite" anderer Teams) ist die Plus-Tiefe."""
    cfg = _get_cfg()
    fav_id = cfg.get("favorite_team_id")
    if not (fav_id and int(fav_id) == team_id):
        _require_liga_plus()
    api_key = _get_api_key(cfg)
    if not api_key:
        raise HTTPException(400, "Liga nicht konfiguriert")
    return LigaService(api_key).get_team_focus(team_id)


@router.get("/liga/team-squad")
def get_team_squad(team_id: int = Query(...)) -> dict[str, Any]:
    """Kader eines Teams inkl. Trikotnummern — funktioniert für National- und Vereinsmannschaften."""
    _require_liga_plus()
    cfg = _get_cfg()
    api_key = _get_api_key(cfg)
    if not api_key:
        raise HTTPException(400, "Liga nicht konfiguriert")
    data = LigaService(api_key).get_team_squad(team_id)
    if not data:
        raise HTTPException(404, "Team nicht gefunden oder kein Kader verfügbar")
    return data


@router.get("/liga/tm/img")
def proxy_tm_image(url: str = Query(...)) -> Response:
    """TM-Bild-Proxy mit Disk-Cache — überlebt Container-Neustarts."""
    parsed = urllib.parse.urlparse(url)
    if not (parsed.scheme == "https" and parsed.hostname and
            (parsed.hostname.endswith(".transfermarkt.com") or
             parsed.hostname.endswith(".transfermarkt.technology") or
             parsed.hostname == "img.transfermarkt.com" or
             parsed.hostname == "tmssl.akamaized.net")):
        raise HTTPException(403, "Nur Transfermarkt-Bilder erlaubt")

    try:
        _IMG_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    img_key   = hashlib.sha256(url.encode()).hexdigest()
    img_path  = _IMG_CACHE_DIR / img_key
    meta_path = _IMG_CACHE_DIR / f"{img_key}.meta"

    # Aus Disk-Cache servieren wenn vorhanden
    if img_path.exists() and meta_path.exists():
        try:
            ct = json.loads(meta_path.read_text()).get("ct", "image/jpeg")
            return Response(
                content=img_path.read_bytes(),
                media_type=ct,
                headers={"Cache-Control": "public, max-age=2592000"},  # 30 Tage
            )
        except Exception:
            pass

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.transfermarkt.de/",
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
            ct = resp.headers.get("Content-Type", "image/jpeg")
        try:
            img_path.write_bytes(data)
            meta_path.write_text(json.dumps({"ct": ct}))
        except Exception:
            pass
        return Response(
            content=data,
            media_type=ct,
            headers={"Cache-Control": "public, max-age=2592000"},
        )
    except Exception:
        raise HTTPException(502, "Bild konnte nicht geladen werden")


@router.delete("/liga/cache")
def clear_liga_cache() -> dict[str, Any]:
    """Löscht alle TM-Disk-Caches (Kader, Spieler-Profile, Suchen) + In-Memory-Caches."""
    import shutil
    removed: list[str] = []
    for sub in ("kader", "players", "searches", "clubs", "persons", "player_transfers", "focus"):
        d = pathlib.Path(f"/data/tm_cache/{sub}")
        if d.exists():
            try:
                shutil.rmtree(d)
                removed.append(sub)
            except Exception:
                pass
    LigaService.invalidate_cache()
    return {"cleared": removed}


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
