"""OpenLigaDB-Backend für das Liga-Display-Modul (BL1/BL2/BL3).

Identische Datenquelle wie der FootballProvider (Voice-Suche), damit
Display und Sprachanfragen immer konsistent sind.
Kein API-Key, keine Rate-Limits.

Liefert Daten im gleichen Format wie LigaService (football-data.org),
sodass das Frontend keine Änderungen braucht.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

BASE = "https://api.openligadb.de"

# football-data.org Code → OpenLigaDB Kürzel
_FDORG_TO_OLDB: dict[str, str] = {
    "BL1": "bl1",
    "BL2": "bl2",
    "BL3": "bl3",
}

COMPETITION_NAMES: dict[str, str] = {
    "BL1": "1. Bundesliga",
    "BL2": "2. Bundesliga",
    "BL3": "3. Liga",
}

STATE_TTL    = 55    # Live-Daten
TABLE_TTL    = 300   # Tabelle 5 Min
TEAMS_TTL    = 21600 # Teams 6h

_state_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_table_cache: dict[str, tuple[float, list[dict]]]     = {}
_teams_cache: dict[str, tuple[float, list[dict]]]     = {}


def _fetch(url: str) -> Any:
    try:
        req = Request(url, headers={"User-Agent": "robot-core/1.0"})
        with urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode())
    except (URLError, OSError, json.JSONDecodeError, Exception):
        return None


def _season_year() -> int:
    now = datetime.now()
    return now.year if now.month >= 8 else now.year - 1


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _infer_live(match: dict[str, Any]) -> bool:
    """Zeitbasierte Live-Erkennung (OpenLigaDB hat keinen IN_PLAY-Status)."""
    if match.get("status") in {"IN_PLAY", "PAUSED"}:
        return True
    if match.get("status") != "SCHEDULED":
        return False
    utc = match.get("utcDate")
    if not utc:
        return False
    try:
        kickoff = datetime.fromisoformat(utc.replace("Z", "+00:00"))
        elapsed = (_utc_now() - kickoff).total_seconds() / 60
        return 0 <= elapsed <= 130
    except Exception:
        return False


def _oldb_to_match(m: dict[str, Any], fdorg_code: str) -> dict[str, Any]:
    """Konvertiert OpenLigaDB-Match in das LigaService/football-data.org-Format."""
    t1 = m.get("team1") or {}
    t2 = m.get("team2") or {}

    # Score aus matchResults
    ht_score = ft_score = None
    for r in m.get("matchResults") or []:
        if r.get("resultTypeID") == 1:
            ht_score = {"home": r.get("pointsTeam1"), "away": r.get("pointsTeam2")}
        elif r.get("resultTypeID") == 2:
            ft_score = {"home": r.get("pointsTeam1"), "away": r.get("pointsTeam2")}

    # Status
    if m.get("matchIsFinished"):
        status = "FINISHED"
    else:
        status = "SCHEDULED"  # _infer_live() erkennt laufende Spiele zeitbasiert

    # Goals aus OpenLigaDB-Format konvertieren
    goals: list[dict[str, Any]] = []
    home_short = t1.get("shortName") or t1.get("teamName") or ""
    away_short = t2.get("shortName") or t2.get("teamName") or ""
    prev_s1 = prev_s2 = 0
    for g in sorted(m.get("goals") or [], key=lambda x: x.get("matchMinute") or 0):
        s1 = g.get("scoreTeam1", prev_s1) or prev_s1
        s2 = g.get("scoreTeam2", prev_s2) or prev_s2
        team_short = home_short if s1 > prev_s1 else (away_short if s2 > prev_s2 else "")
        prev_s1, prev_s2 = s1, s2
        minute = g.get("matchMinute")
        comment = g.get("comment") or ""
        goal_type = (
            "PENALTY"   if g.get("isPenalty")
            else "OWN_GOAL" if g.get("isOwnGoal")
            else "REGULAR"
        )
        goals.append({
            "minute":     minute,
            "injuryTime": int(comment.lstrip("+")) if comment.startswith("+") and comment[1:].isdigit() else None,
            "scorer":     {"name": g.get("goalGetterName") or ""},
            "team":       {"shortName": team_short},
            "type":       goal_type,
        })

    utc_date = m.get("matchDateTimeUTC") or ""
    if utc_date and not utc_date.endswith("Z") and "+" not in utc_date:
        utc_date += "Z"

    return {
        "id":       m.get("matchID"),
        "utcDate":  utc_date,
        "status":   status,
        "matchday": (m.get("group") or {}).get("groupOrderID"),
        "stage":    "REGULAR_SEASON",
        "homeTeam": {
            "id":        t1.get("teamId"),
            "name":      t1.get("teamName") or "",
            "shortName": t1.get("shortName") or t1.get("teamName") or "",
            "tla":       (t1.get("shortName") or "")[:3].upper(),
            "crest":     t1.get("teamIconUrl") or "",
        },
        "awayTeam": {
            "id":        t2.get("teamId"),
            "name":      t2.get("teamName") or "",
            "shortName": t2.get("shortName") or t2.get("teamName") or "",
            "tla":       (t2.get("shortName") or "")[:3].upper(),
            "crest":     t2.get("teamIconUrl") or "",
        },
        "score": {
            "fullTime": ft_score or {"home": None, "away": None},
            "halfTime": ht_score or {"home": None, "away": None},
        },
        "goals":    goals,
        "bookings": [],
    }


def _get_current_matches(oldb_code: str) -> list[dict[str, Any]]:
    """Aktueller Spieltag von OpenLigaDB. Zwei-Schritt-Strategie."""
    # Versuch 1: einfach
    data = _fetch(f"{BASE}/getmatchdata/{oldb_code}")
    matches = data if isinstance(data, list) else []

    # Versuch 2: explizite Gruppe
    if not matches:
        group = _fetch(f"{BASE}/getcurrentgroup/{oldb_code}")
        if isinstance(group, dict):
            gid = group.get("groupOrderID") or group.get("groupOrderId")
            season = _season_year()
            if gid is not None:
                data2 = _fetch(f"{BASE}/getmatchdata/{oldb_code}/{season}/{gid}")
                matches = data2 if isinstance(data2, list) else []

    return matches


def get_state(fdorg_code: str) -> dict[str, Any] | None:
    """Liefert Spieltag-State im LigaService-Format. None bei Fehler."""
    from app.services.tournament_service import _resolve_matchday

    oldb_code = _FDORG_TO_OLDB.get(fdorg_code)
    if not oldb_code:
        return None

    now = time.time()
    cached = _state_cache.get(fdorg_code)
    if cached and (now - cached[0]) < STATE_TTL:
        return cached[1]

    raw = _get_current_matches(oldb_code)
    if not raw:
        return cached[1] if cached else None

    matches = [_oldb_to_match(m, fdorg_code) for m in raw]

    matchday_nr, matchday_matches = _resolve_matchday(matches, None)
    matchday_matches.sort(key=lambda m: m.get("utcDate") or "")

    live = [m for m in matchday_matches if m.get("status") in {"IN_PLAY", "PAUSED"}]
    if not live:
        live = [m for m in matchday_matches if _infer_live(m)]

    # Live-Score aus Goals ableiten wenn fullTime noch null
    for m in live:
        ft = m.get("score", {}).get("fullTime", {})
        if ft.get("home") is None and m.get("goals"):
            last = m["goals"][-1]
            # Score rückrechnen aus letztem Tor-Eintrag des raw-Matches
            raw_m = next((r for r in raw if r.get("matchID") == m.get("id")), None)
            if raw_m:
                raw_goals = sorted(raw_m.get("goals") or [], key=lambda g: g.get("matchMinute") or 0)
                if raw_goals:
                    lg = raw_goals[-1]
                    ft["home"] = lg.get("scoreTeam1", 0)
                    ft["away"] = lg.get("scoreTeam2", 0)

    result: dict[str, Any] = {
        "code":         fdorg_code,
        "name":         COMPETITION_NAMES.get(fdorg_code, fdorg_code),
        "matchday_nr":  matchday_nr,
        "matches":      matchday_matches,
        "live":         live,
    }
    _state_cache[fdorg_code] = (now, result)
    return result


def get_standings(fdorg_code: str) -> dict[str, Any] | None:
    """Tabelle im LigaService-Format. None bei Fehler."""
    oldb_code = _FDORG_TO_OLDB.get(fdorg_code)
    if not oldb_code:
        return None

    now = time.time()
    cached = _table_cache.get(fdorg_code)
    if cached and (now - cached[0]) < TABLE_TTL:
        return {
            "code":  fdorg_code,
            "name":  COMPETITION_NAMES.get(fdorg_code, fdorg_code),
            "table": cached[1],
        }

    season = _season_year()
    data = _fetch(f"{BASE}/getbltable/{oldb_code}/{season}")
    if not isinstance(data, list):
        if cached:
            return {"code": fdorg_code, "name": COMPETITION_NAMES.get(fdorg_code, fdorg_code), "table": cached[1]}
        return None

    table = []
    for i, e in enumerate(data, start=1):
        table.append({
            "position":      i,
            "team": {
                "id":        e.get("teamInfoId"),
                "name":      e.get("teamName") or "",
                "shortName": e.get("shortName") or e.get("teamName") or "",
                "crest":     e.get("teamIconUrl") or "",
            },
            "playedGames":   e.get("matches", 0),
            "won":           e.get("won", 0),
            "draw":          e.get("draw", 0),
            "lost":          e.get("lost", 0),
            "points":        e.get("points", 0),
            "goalsFor":      e.get("goals", 0),
            "goalsAgainst":  e.get("opponentGoals", 0),
            "goalDifference": e.get("goals", 0) - e.get("opponentGoals", 0),
        })

    _table_cache[fdorg_code] = (now, table)
    return {
        "code":  fdorg_code,
        "name":  COMPETITION_NAMES.get(fdorg_code, fdorg_code),
        "table": table,
    }


def get_teams(fdorg_code: str) -> list[dict[str, Any]]:
    """Teams aus getbltable ableiten (getteams-Endpoint existiert nicht bei OpenLigaDB)."""
    oldb_code = _FDORG_TO_OLDB.get(fdorg_code)
    if not oldb_code:
        return []

    now = time.time()
    cached = _teams_cache.get(fdorg_code)
    if cached and (now - cached[0]) < TEAMS_TTL:
        return cached[1]

    season = _season_year()
    data = _fetch(f"{BASE}/getbltable/{oldb_code}/{season}")
    if not isinstance(data, list):
        return cached[1] if cached else []

    teams = [
        {
            "id":           e.get("teamInfoId"),
            "name":         e.get("teamName") or "",
            "shortName":    e.get("shortName") or e.get("teamName") or "",
            "tla":          (e.get("shortName") or "")[:3].upper(),
            "crest":        e.get("teamIconUrl") or "",
            "league_code":  fdorg_code,
            "league_name":  COMPETITION_NAMES.get(fdorg_code, fdorg_code),
        }
        for e in data
    ]
    teams.sort(key=lambda t: t.get("name") or "")
    _teams_cache[fdorg_code] = (now, teams)
    return teams
