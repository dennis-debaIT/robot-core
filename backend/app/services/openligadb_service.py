"""OpenLigaDB-Integration — kostenlose Tor-Events für WM + Bundesliga.

Kein API-Key, keine Rate-Limits. Tore werden innerhalb weniger Minuten
eingetragen. Karten sind in OpenLigaDB nicht verfügbar.

Matching-Strategie:
  1. 3-Letter-Code (WM-Nationalteams: OpenLigaDB shortName == football-data.org tla)
  2. Normierter Namensvergleich (Fallback für Clubteams / abweichende Codes)
"""
from __future__ import annotations

import json
import time
import unicodedata
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

BASE_URL = "https://api.openligadb.de"

# football-data.org Wettbewerbs-Code → OpenLigaDB Kürzel
_COMP_MAP: dict[str, str] = {
    "WC":  "wm2026",
    "BL1": "bl1",
    "BL2": "bl2",
    "BL3": "bl3",
}

# Cache: oldb_key → (timestamp, list[match_dict])
_MATCHDAY_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
CACHE_TTL = 90  # etwas länger als football-data.org-Zyklus (kein Rate-Limit-Problem)


def _fetch_json(url: str) -> Any:
    try:
        with urlopen(url, timeout=8) as resp:
            return json.loads(resp.read().decode())
    except (URLError, OSError, json.JSONDecodeError, Exception):
        return None


def _normalize(name: str) -> str:
    """Lowercase, Umlaute/Akzente entfernen, Sonderzeichen vereinfachen."""
    name = name.lower()
    # Umlaute und Akzente
    nfkd = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in nfkd if not unicodedata.combining(c))
    for src, dst in [("-", " "), (".", ""), ("'", ""), ("ß", "ss")]:
        name = name.replace(src, dst)
    return name.strip()


def _names_match(n1: str, n2: str) -> bool:
    a, b = _normalize(n1), _normalize(n2)
    return a == b or a in b or b in a


def _get_oldb_matches(oldb_code: str) -> list[dict[str, Any]]:
    now = time.time()
    cached = _MATCHDAY_CACHE.get(oldb_code)
    if cached and (now - cached[0]) < CACHE_TTL:
        return cached[1]
    data = _fetch_json(f"{BASE_URL}/getmatchdata/{oldb_code}")
    matches: list[dict[str, Any]] = data if isinstance(data, list) else []
    _MATCHDAY_CACHE[oldb_code] = (now, matches)
    return matches


def _find_oldb_match(
    oldb_matches: list[dict[str, Any]],
    home_tla: str,
    away_tla: str,
    home_name: str,
    away_name: str,
) -> dict[str, Any] | None:
    """Findet das passende OpenLigaDB-Spiel per TLA oder Namensvergleich."""
    home_tla_up = (home_tla or "").upper()
    away_tla_up = (away_tla or "").upper()

    for m in oldb_matches:
        t1 = m.get("team1") or {}
        t2 = m.get("team2") or {}
        s1 = (t1.get("shortName") or "").upper()
        s2 = (t2.get("shortName") or "").upper()

        # 1) TLA-Match
        if home_tla_up and away_tla_up:
            if s1 == home_tla_up and s2 == away_tla_up:
                return m
            if s1 == away_tla_up and s2 == home_tla_up:
                return m

        # 2) Name-Fallback
        n1 = t1.get("teamName") or ""
        n2 = t2.get("teamName") or ""
        if _names_match(home_name, n1) and _names_match(away_name, n2):
            return m
        if _names_match(home_name, n2) and _names_match(away_name, n1):
            return m

    return None


def _convert_goals(
    raw_goals: list[dict[str, Any]],
    home_short: str,
    away_short: str,
) -> list[dict[str, Any]]:
    """Konvertiert OpenLigaDB-Tore in das football-data.org-Format."""
    result = []
    prev_s1 = prev_s2 = 0
    for g in sorted(raw_goals, key=lambda x: x.get("matchMinute") or 0):
        s1 = g.get("scoreTeam1", prev_s1)
        s2 = g.get("scoreTeam2", prev_s2)
        if s1 > prev_s1:
            team_short = home_short
        elif s2 > prev_s2:
            team_short = away_short
        else:
            team_short = ""
        prev_s1, prev_s2 = s1, s2

        goal_type = (
            "PENALTY"   if g.get("isPenalty")
            else "OWN_GOAL" if g.get("isOwnGoal")
            else "REGULAR"
        )
        minute = g.get("matchMinute")
        comment = g.get("comment") or ""
        result.append({
            "minute":      minute,
            "injuryTime":  int(comment.lstrip("+")) if comment.startswith("+") and comment[1:].isdigit() else None,
            "scorer":      {"name": g.get("goalGetterName") or ""},
            "team":        {"shortName": team_short},
            "type":        goal_type,
        })
    return result


def enrich_goals(
    match: dict[str, Any],
    competition_code: str,
) -> None:
    """Ergänzt match["goals"] aus OpenLigaDB wenn das Feld leer ist.

    Modifiziert `match` in-place. Macht nichts wenn goals bereits vorhanden
    oder keine OpenLigaDB-Daten für den Wettbewerb verfügbar sind.
    """
    if match.get("goals"):
        return  # bereits befüllt — nicht überschreiben

    oldb_code = _COMP_MAP.get((competition_code or "").upper())
    if not oldb_code:
        return

    home = match.get("homeTeam") or {}
    away = match.get("awayTeam") or {}
    home_tla  = home.get("tla")  or ""
    away_tla  = away.get("tla")  or ""
    home_name = home.get("name") or home.get("shortName") or ""
    away_name = away.get("name") or away.get("shortName") or ""

    oldb_matches = _get_oldb_matches(oldb_code)
    oldb_match = _find_oldb_match(oldb_matches, home_tla, away_tla, home_name, away_name)
    if not oldb_match:
        return

    raw_goals: list[dict] = oldb_match.get("goals") or []
    if not raw_goals:
        return

    home_short = (home.get("shortName") or home_name)
    away_short = (away.get("shortName") or away_name)
    match["goals"] = _convert_goals(raw_goals, home_short, away_short)
