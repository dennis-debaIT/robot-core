from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

BASE_URL = "https://api.football-data.org/v4"
CACHE_TTL = 55  # etwas unter 60s damit wir die 10 req/min-Grenze sicher einhalten

_LIVE = {"IN_PLAY", "PAUSED"}
_ACTIVE = {"IN_PLAY", "PAUSED", "SCHEDULED", "TIMED"}
_DONE = {"FINISHED"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _resolve_matchday(all_matches: list[dict[str, Any]], hint: int | None) -> tuple[int | None, list[dict[str, Any]]]:
    """Ermittelt den aktuellen Spieltag aus den Match-Daten selbst.

    Rückgabe: (matchday_nr, matches_for_that_day)
    matchday_nr ist None bei KO-Runden ohne Spieltag-Nummerierung.
    """
    # 1) Wenn API-Hint vorhanden → direkt nutzen
    if hint is not None:
        matches = [m for m in all_matches if m.get("matchday") == hint]
        if matches:
            return hint, matches

    # 2) Gruppen-Phase: alle Matches mit matchday-Nummer vorhanden?
    group_matches = [m for m in all_matches if m.get("matchday") is not None]
    if group_matches:
        now = _utc_now()

        # a) Gibt es gerade laufende oder bald startende Spiele? → deren Spieltag
        for m in group_matches:
            if m.get("status") in _LIVE:
                day = m["matchday"]
                return day, [x for x in group_matches if x.get("matchday") == day]

        # b) Nächster geplanter Spieltag (frühestes Datum in der Zukunft)
        upcoming = [m for m in group_matches if m.get("status") in {"SCHEDULED", "TIMED"}]
        if upcoming:
            upcoming.sort(key=lambda x: x.get("utcDate") or "")
            day = upcoming[0]["matchday"]
            return day, [x for x in group_matches if x.get("matchday") == day]

        # c) Alle Gruppenspiele abgeschlossen → letzter Spieltag
        finished = [m for m in group_matches if m.get("status") in _DONE]
        if finished:
            finished.sort(key=lambda x: x.get("utcDate") or "")
            day = finished[-1]["matchday"]
            return day, [x for x in group_matches if x.get("matchday") == day]

        return None, group_matches  # Fallback: alles

    # 3) KO-Phase (kein matchday): aktive Stage finden
    now = _utc_now()
    stages_order: list[str] = []
    for m in all_matches:
        s = m.get("stage") or ""
        if s and s not in stages_order:
            stages_order.append(s)

    # Prüfe Stages von vorn (Gruppe → KO) und wähle die früheste mit aktiven Spielen
    for stage in stages_order:
        stage_matches = [m for m in all_matches if m.get("stage") == stage]
        if any(m.get("status") in _ACTIVE for m in stage_matches):
            return None, stage_matches

    # Fallback: letzte Stage (FINAL oder ähnliches)
    active_stage = stages_order[-1] if stages_order else None
    if active_stage:
        return None, [m for m in all_matches if m.get("stage") == active_stage]
    return None, []


STANDINGS_TTL = 300  # Tabelle ändert sich selten — 5 Min reichen


class TournamentService:
    _cache: dict[str, Any] = {}
    _cache_ts: float = 0.0
    _cache_code: str = ""
    _standings_cache: dict[str, Any] = {}
    _standings_cache_ts: float = 0.0
    _standings_cache_code: str = ""

    def __init__(self, api_key: str, competition_code: str = "WC") -> None:
        self.api_key = api_key
        self.competition_code = competition_code.upper()

    def _fetch(self, path: str) -> dict[str, Any] | None:
        try:
            req = Request(
                f"{BASE_URL}{path}",
                headers={"X-Auth-Token": self.api_key},
            )
            with urlopen(req, timeout=8) as resp:
                return json.loads(resp.read().decode())
        except (URLError, OSError, json.JSONDecodeError, Exception):
            return None

    def get_current(self) -> dict[str, Any]:
        now = time.time()
        if (
            self._cache
            and self._cache_code == self.competition_code
            and (now - self._cache_ts) < CACHE_TTL
        ):
            return self._cache

        data = self._fetch(f"/competitions/{self.competition_code}/matches")
        if not data:
            return self._cache or {"live": [], "matchday": [], "matchday_nr": None, "error": True}

        all_matches: list[dict[str, Any]] = data.get("matches", [])
        competition: dict[str, Any] = data.get("competition", {})

        # currentMatchday kann direkt auf competition liegen oder in currentSeason
        api_hint: int | None = (
            competition.get("currentMatchday")
            or (competition.get("currentSeason") or {}).get("currentMatchday")
        )

        live_matches = [m for m in all_matches if m.get("status") in _LIVE]

        # Aktuellen Spieltag aus Match-Daten ermitteln (robust, unabhängig vom API-Hint)
        matchday_nr, matchday_matches = _resolve_matchday(all_matches, api_hint)

        matchday_matches.sort(key=lambda m: m.get("utcDate") or "")

        result: dict[str, Any] = {
            "live": live_matches,
            "matchday": matchday_matches,
            "matchday_nr": matchday_nr,
            "competition_name": competition.get("name", "Turnier"),
        }
        TournamentService._cache = result
        TournamentService._cache_ts = now
        TournamentService._cache_code = self.competition_code
        return result

    def get_standings(self) -> dict[str, Any]:
        now = time.time()
        if (
            self._standings_cache
            and self._standings_cache_code == self.competition_code
            and (now - self._standings_cache_ts) < STANDINGS_TTL
        ):
            return self._standings_cache

        data = self._fetch(f"/competitions/{self.competition_code}/standings")
        if not data:
            return self._standings_cache or {"groups": [], "error": True}

        # Nur Gesamttabelle (TOTAL) der Gruppenphase
        groups = [
            {
                "group": s.get("group", ""),
                "table": s.get("table", []),
            }
            for s in data.get("standings", [])
            if s.get("type") == "TOTAL" and s.get("group")
        ]

        result: dict[str, Any] = {"groups": groups}
        TournamentService._standings_cache = result
        TournamentService._standings_cache_ts = now
        TournamentService._standings_cache_code = self.competition_code
        return result

    @classmethod
    def invalidate_cache(cls) -> None:
        cls._cache = {}
        cls._cache_ts = 0.0
        cls._standings_cache = {}
        cls._standings_cache_ts = 0.0
