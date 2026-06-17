"""worldcup26.ir — kostenlose WM-2026-Daten mit Live-Scores und Torschützen.

Kein API-Key, keine Rate-Limits.
Tore und Scores werden zeitnah gepflegt (reagiert schnell auf VAR-Entscheide).
Scorer-Namen in englischer Transliteration (manchmal ungenau).

Matching-Strategie:
  1. fifa_code / TLA  (Teams-Endpoint → team_id→TLA-Map)
  2. Normierter Namensvergleich (Fallback)
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

BASE_URL = "https://worldcup26.ir"

GAMES_TTL = 55      # Live-Daten unter 60s
TEAMS_TTL = 21600   # Team-Map 6h (ändert sich nur im Sommer)

_games_cache: tuple[float, list[dict[str, Any]]] = (0.0, [])
_teams_map:   dict[str, str] = {}   # team_id → fifa_code (TLA)
_teams_ts:    float = 0.0


def _fetch_json(url: str) -> Any:
    try:
        with urlopen(url, timeout=8) as resp:
            return json.loads(resp.read().decode())
    except (URLError, OSError, json.JSONDecodeError, Exception):
        return None


def _normalize(name: str) -> str:
    name = name.lower()
    nfkd = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in nfkd if not unicodedata.combining(c))
    for src, dst in [("-", " "), (".", ""), ("'", "")]:
        name = name.replace(src, dst)
    return name.strip()


def _names_match(n1: str, n2: str) -> bool:
    a, b = _normalize(n1), _normalize(n2)
    return a == b or a in b or b in a


def _get_teams_map() -> dict[str, str]:
    """Liefert team_id → fifa_code (TLA). Cached 6h."""
    global _teams_map, _teams_ts
    now = time.time()
    if _teams_map and (now - _teams_ts) < TEAMS_TTL:
        return _teams_map
    data = _fetch_json(f"{BASE_URL}/get/teams")
    if not isinstance(data, dict):
        return _teams_map
    mapping: dict[str, str] = {}
    for t in data.get("teams", []):
        tid  = str(t.get("id") or "")
        code = (t.get("fifa_code") or "").upper()
        if tid and code:
            mapping[tid] = code
    _teams_map = mapping
    _teams_ts  = now
    return mapping


def _get_games() -> list[dict[str, Any]]:
    """Alle WM-Spiele von worldcup26.ir. Cached 55s."""
    global _games_cache
    now = time.time()
    if now - _games_cache[0] < GAMES_TTL:
        return _games_cache[1]

    data = _fetch_json(f"{BASE_URL}/get/games")
    games: list[dict[str, Any]] = []
    if isinstance(data, dict):
        teams_map = _get_teams_map()
        for g in data.get("games", []):
            g["_home_tla"] = teams_map.get(str(g.get("home_team_id") or ""), "")
            g["_away_tla"] = teams_map.get(str(g.get("away_team_id") or ""), "")
            games.append(g)
    _games_cache = (now, games)
    return games


def _find_game(
    games: list[dict[str, Any]],
    home_tla: str, away_tla: str,
    home_name: str, away_name: str,
) -> tuple[dict[str, Any], bool] | tuple[None, None]:
    """Findet passendes Spiel. Rückgabe: (game, home_is_home_team)."""
    h_up = (home_tla or "").upper()
    a_up = (away_tla or "").upper()

    for g in games:
        ht = g.get("_home_tla", "")
        at = g.get("_away_tla", "")
        hn = g.get("home_team_name_en", "")
        an = g.get("away_team_name_en", "")

        # 1) TLA-Match
        if h_up and a_up:
            if ht == h_up and at == a_up:
                return g, True
            if ht == a_up and at == h_up:
                return g, False

        # 2) Name-Fallback
        if _names_match(home_name, hn) and _names_match(away_name, an):
            return g, True
        if _names_match(home_name, an) and _names_match(away_name, hn):
            return g, False

    return None, None


def _parse_scorers(raw: str | None, team_short: str) -> list[dict[str, Any]]:
    """Parst PostgreSQL-Array-Format: {\"Name Minute'\",\"Name2 Minute2'\"}"""
    if not raw or raw.lower() in ("null", ""):
        return []
    s = raw.strip("{}")
    if not s:
        return []

    parts = re.split(r'",\s*"', s)
    result: list[dict[str, Any]] = []
    for p in parts:
        p = p.strip('"').strip()
        if not p:
            continue

        # Typ-Erkennung: (p) = Elfmeter, (og) = Eigentor
        goal_type = "REGULAR"
        if "(p)" in p:
            goal_type = "PENALTY"
            p = p.replace("(p)", "").strip()
        elif "(og)" in p:
            goal_type = "OWN_GOAL"
            p = p.replace("(og)", "").strip()

        # Minute parsen: "Name 27'" oder "Name 90+5'"
        m = re.match(r"^(.*?)\s+(\d+)(?:\+(\d+))?'?\s*$", p)
        if m:
            name   = m.group(1).strip()
            minute = int(m.group(2))
            injury = int(m.group(3)) if m.group(3) else None
        else:
            name   = p
            minute = 0
            injury = None

        result.append({
            "minute":     minute,
            "injuryTime": injury,
            "scorer":     {"name": name},
            "team":       {"shortName": team_short},
            "type":       goal_type,
        })
    return result


def enrich_match(match: dict[str, Any]) -> None:
    """Ergänzt WM-Match mit Score + Goals aus worldcup26.ir.

    Score wird übernommen solange das Spiel gestartet hat (Live oder beendet).
    Goals werden nur gesetzt wenn noch keine vorhanden sind.
    Modifiziert `match` in-place.
    """
    home = match.get("homeTeam") or {}
    away = match.get("awayTeam") or {}
    home_tla  = home.get("tla")  or ""
    away_tla  = away.get("tla")  or ""
    home_name = home.get("name") or home.get("shortName") or ""
    away_name = away.get("name") or away.get("shortName") or ""

    games = _get_games()
    game, home_is_home = _find_game(games, home_tla, away_tla, home_name, away_name)
    if not game:
        return

    # Nur aktive/beendete Spiele aktualisieren (keine künftigen 0:0)
    elapsed = game.get("time_elapsed", "")
    if elapsed == "notstarted":
        return

    # Score aktualisieren (worldcup26 reagiert schneller auf VAR als football-data.org)
    try:
        h_sc = int(game.get("home_score") or 0)
        a_sc = int(game.get("away_score") or 0)
    except (ValueError, TypeError):
        h_sc = a_sc = 0

    home_score = h_sc if home_is_home else a_sc
    away_score = a_sc if home_is_home else h_sc

    score = match.setdefault("score", {})
    ft    = score.setdefault("fullTime", {})
    ft["home"] = home_score
    ft["away"] = away_score

    # Goals aus Scorers aufbauen (nur wenn noch keine vorhanden)
    if not match.get("goals"):
        home_short = home.get("shortName") or home_name
        away_short = away.get("shortName") or away_name

        h_raw = game.get("home_scorers") if home_is_home else game.get("away_scorers")
        a_raw = game.get("away_scorers") if home_is_home else game.get("home_scorers")
        h_sh  = home_short if home_is_home else away_short
        a_sh  = away_short if home_is_home else home_short

        goals: list[dict[str, Any]] = []
        goals.extend(_parse_scorers(h_raw, h_sh))
        goals.extend(_parse_scorers(a_raw, a_sh))
        goals.sort(key=lambda g: g.get("minute") or 0)
        if goals:
            match["goals"] = goals
