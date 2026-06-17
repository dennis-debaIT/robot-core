"""Transfermarkt-Vereinsdaten via community API (transfermarkt-api.fly.dev).

Scraping-basiert — externe Abhängigkeit. Aggressive In-Memory-Caches
(7 Tage / 24 h / 6 h) halten die Anzahl externer Anfragen minimal.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

_TM_BASE = "https://transfermarkt-api.fly.dev"

_SEARCH_TTL   = 7 * 86_400   # TM-IDs ändern sich nie
_PROFILE_TTL  = 24 * 3_600   # Profildaten (Stadium, Gründung, …)
_PLAYERS_TTL  = 6 * 3_600    # Marktwerte aktualisieren sich öfter
_ENRICHED_TTL = 6 * 3_600    # angereicherter Kader (Bild + Rückennummer)

_cache: dict[str, dict[str, Any]] = {}


def _cached(key: str, ttl: float) -> Any | None:
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < ttl:
        return entry["data"]
    return None


def _store(key: str, data: Any) -> None:
    _cache[key] = {"data": data, "ts": time.time()}


def _fetch_player_enriched(player_id: str) -> tuple[str, dict]:
    """Profilbild und Rückennummer eines Spielers per /players/{id}/profile."""
    data = _get(f"/players/{player_id}/profile")
    if not data:
        return player_id, {}
    result: dict = {}
    image = data.get("imageURL") or data.get("image") or data.get("profileImage")
    if image:
        result["image"] = image
    shirt = data.get("shirtNumber") if data.get("shirtNumber") is not None else data.get("jerseyNumber")
    if shirt is not None:
        result["shirtNumber"] = shirt
    return player_id, result


def _get(path: str) -> dict | None:
    url = f"{_TM_BASE}{path}"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "robot-core/1.0", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=14) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


class TransfermarktService:
    def search_club_id(self, name: str) -> str | None:
        """TM-ID per Namenssuche — bevorzugt deutschen Treffer."""
        key = f"tm_search:{name.lower().strip()}"
        cached = _cached(key, _SEARCH_TTL)
        if cached is not None:
            return cached
        data = _get(f"/clubs/search/{urllib.parse.quote(name)}")
        results: list[dict] = (data or {}).get("results") or []
        tm_id: str | None = None
        for r in results:
            country = str(r.get("country") or "").lower()
            if country in ("germany", "deutschland"):
                tm_id = str(r["id"])
                break
        if tm_id is None and results:
            tm_id = str(results[0]["id"])
        if tm_id:
            _store(key, tm_id)
        return tm_id

    def get_club_profile(self, team_name: str) -> dict | None:
        tm_id = self.search_club_id(team_name)
        if not tm_id:
            return None
        key = f"tm_profile:{tm_id}"
        cached = _cached(key, _PROFILE_TTL)
        if cached is not None:
            return cached
        data = _get(f"/clubs/{tm_id}/profile")
        if data:
            _store(key, data)
        return data

    def get_club_players(self, team_name: str) -> list[dict] | None:
        tm_id = self.search_club_id(team_name)
        if not tm_id:
            return None
        key = f"tm_players:{tm_id}"
        cached = _cached(key, _PLAYERS_TTL)
        if cached is not None:
            return cached
        data = _get(f"/clubs/{tm_id}/players")
        players: list[dict] = (data or {}).get("players") or []
        if players:
            _store(key, players)
        return players or None

    def get_club_players_enriched(self, team_name: str) -> list[dict] | None:
        """Kader-Liste angereichert mit Profilbild und Rückennummer via paralleler Einzel-Abfragen."""
        tm_id = self.search_club_id(team_name)
        if not tm_id:
            return None
        key = f"tm_players_enriched:{tm_id}"
        cached = _cached(key, _ENRICHED_TTL)
        if cached is not None:
            return cached
        players = self.get_club_players(team_name)
        if not players:
            return players
        enrichment: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = {
                ex.submit(_fetch_player_enriched, str(p["id"])): str(p["id"])
                for p in players if p.get("id")
            }
            for f in as_completed(futs, timeout=30):
                pid = futs[f]
                try:
                    pid, info = f.result(timeout=8)
                    enrichment[pid] = info
                except Exception:
                    enrichment[pid] = {}
        enriched = [dict(p, **enrichment.get(str(p.get("id")), {})) for p in players]
        _store(key, enriched)
        return enriched
