"""Transfermarkt-Vereinsdaten via community API (transfermarkt-api.fly.dev).

Scraping-basiert — externe Abhängigkeit.
Disk-Cache unter /data/tm_cache/ überlebt Container-Neustarts; Spieler-Profile
werden 30 Tage gecacht, Vereins-Profile 24 h.
"""
from __future__ import annotations

import json
import pathlib
import re
import time
import urllib.parse
import urllib.request
from typing import Any

_TM_BASE = "https://transfermarkt-api.fly.dev"

_SEARCH_TTL      = 7 * 86_400   # TM-IDs ändern sich kaum
_CLUB_TTL        = 24 * 3_600   # Vereinsprofil (Stadium, Gründung, …)
_PLAYERS_TTL     = 6 * 3_600    # Kaderliste (Marktwerte)
_PLAYER_DISK_TTL = 30 * 86_400  # Spieler-Einzel-Profil: 30 Tage Disk-Cache

_cache: dict[str, dict[str, Any]] = {}

_PLAYER_CACHE_DIR  = pathlib.Path("/data/tm_cache/players")
_SEARCH_CACHE_DIR  = pathlib.Path("/data/tm_cache/searches")


def _cached(key: str, ttl: float) -> Any | None:
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < ttl:
        return entry["data"]
    return None


def _store(key: str, data: Any) -> None:
    _cache[key] = {"data": data, "ts": time.time()}


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
        """TM-ID per Namenssuche — bevorzugt deutschen Treffer.

        Probiert mehrere Suchbegriffe falls der exakte Name keine Treffer liefert:
        1. Original ("1. FC Heidenheim 1846")
        2. Ohne führende "N. " ("FC Heidenheim 1846")
        3. Ohne abschließende Jahreszahl ("FC Heidenheim")
        """
        key = f"tm_search:{name.lower().strip()}"
        cached = _cached(key, _SEARCH_TTL)
        if cached is not None:
            return cached

        base = name.strip()
        candidates: list[str] = [base]
        c1 = re.sub(r'^\d+\.\s+', '', base)          # "1. FC Köln" → "FC Köln"
        if c1 != base:
            candidates.append(c1)
        c2 = re.sub(r'\s+\d{4}$', '', candidates[-1]) # "FC Heidenheim 1846" → "FC Heidenheim"
        if c2 != candidates[-1]:
            candidates.append(c2)

        tm_id: str | None = None
        for candidate in candidates:
            data = _get(f"/clubs/search/{urllib.parse.quote(candidate)}")
            results: list[dict] = (data or {}).get("results") or []
            for r in results:
                if str(r.get("country") or "").lower() in ("germany", "deutschland"):
                    tm_id = str(r["id"])
                    break
            if tm_id is None and results:
                tm_id = str(results[0]["id"])
            if tm_id:
                break

        if tm_id:
            _store(key, tm_id)
        return tm_id

    def get_club_image_by_id(self, tm_club_id: str) -> str | None:
        """Club-Wappen-URL direkt per TM-Club-ID — 24h gecacht.

        TM player profile enthält kein club.image, daher separater Lookup
        via /clubs/{id}/profile. Ergebnis wird im gleichen Cache wie
        get_club_profile gespeichert.
        """
        key = f"tm_profile:{tm_club_id}"
        cached = _cached(key, _CLUB_TTL)
        if cached is not None:
            return (cached or {}).get("image")
        data = _get(f"/clubs/{tm_club_id}/profile")
        if data:
            _store(key, data)
            return data.get("image")
        return None

    def get_club_profile(self, team_name: str) -> dict | None:
        tm_id = self.search_club_id(team_name)
        if not tm_id:
            return None
        key = f"tm_profile:{tm_id}"
        cached = _cached(key, _CLUB_TTL)
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

    def search_player(self, name: str) -> dict | None:
        """Spieler per Name auf TM suchen — liefert id, marketValue, club, position, age, nationalities.

        7 Tage gecacht: In-Memory (verloren bei Restart) + Disk /data/tm_cache/searches/
        (überlebt Restarts — wichtig für Nationalspieler ohne TM-Vereinskader).
        """
        slug = re.sub(r'[^a-z0-9]', '_', name.lower().strip())
        key = f"tm_player_search:{name.lower().strip()}"
        # 1. In-Memory-Cache
        cached = _cached(key, _SEARCH_TTL)
        if cached is not None:
            return cached
        # 2. Disk-Cache (überlebt Container-Restarts)
        try:
            _SEARCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        cache_path = _SEARCH_CACHE_DIR / f"{slug}.json"
        if cache_path.exists():
            try:
                if time.time() - cache_path.stat().st_mtime < _SEARCH_TTL:
                    data = json.loads(cache_path.read_text(encoding="utf-8"))
                    _store(key, data)
                    return data
            except Exception:
                pass
        # 3. API-Abfrage
        data = _get(f"/players/search/{urllib.parse.quote(name)}")
        results: list[dict] = (data or {}).get("results") or []
        if not results:
            return None
        r = results[0]
        result = {
            "tm_id":         str(r["id"]),
            "name":          r.get("name"),
            "position":      r.get("position"),
            "club":          r.get("club"),
            "age":           r.get("age"),
            "nationalities": r.get("nationalities"),
            "marketValue":   r.get("marketValue"),
        }
        _store(key, result)
        try:
            cache_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        return result

    def get_player_profile(self, player_id: str) -> dict | None:
        """Einzelnes Spieler-Profil mit 30-Tage-Disk-Cache.

        Reihenfolge: In-Memory → Disk → API. Schreibt beim Abruf sofort
        auf Disk, sodass der Cache Container-Neustarts überlebt.
        """
        key = f"tm_player:{player_id}"
        # 1. In-Memory-Cache
        cached = _cached(key, _PLAYER_DISK_TTL)
        if cached is not None:
            return cached
        # 2. Disk-Cache
        try:
            _PLAYER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        cache_path = _PLAYER_CACHE_DIR / f"{player_id}.json"
        if cache_path.exists():
            try:
                age = time.time() - cache_path.stat().st_mtime
                if age < _PLAYER_DISK_TTL:
                    data = json.loads(cache_path.read_text(encoding="utf-8"))
                    _store(key, data)
                    return data
            except Exception:
                pass
        # 3. API-Abfrage
        data = _get(f"/players/{player_id}/profile")
        if data:
            _store(key, data)
            try:
                cache_path.write_text(
                    json.dumps(data, ensure_ascii=False), encoding="utf-8"
                )
            except Exception:
                pass
        return data
