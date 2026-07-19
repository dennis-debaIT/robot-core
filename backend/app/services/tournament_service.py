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

_STAGE_LABEL: dict[str, str] = {
    "LAST_32":        "Runde der letzten 32",
    "LAST_16":        "Achtelfinale",
    "QUARTER_FINALS": "Viertelfinale",
    "SEMI_FINALS":    "Halbfinale",
    "THIRD_PLACE":    "Spiel um Platz 3",
    "FINAL":          "Finale",
}

# Maximale Spieldauer inkl. Verlängerung + Elfmeterschießen (Puffer)
_MAX_MATCH_MINUTES = 130


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _infer_probably_live(match: dict[str, Any]) -> bool:
    """Fallback für Free-Tier: gibt True zurück wenn der Anpfiff vor 0–130 Minuten lag.

    football-data.org Free-Tier aktualisiert den Status nicht immer zuverlässig auf
    IN_PLAY. Dieses Heuristik greift nur wenn status noch SCHEDULED/TIMED ist.
    """
    if match.get("status") in _LIVE:
        return True
    if match.get("status") not in {"SCHEDULED", "TIMED"}:
        return False
    utc_date = match.get("utcDate")
    if not utc_date:
        return False
    try:
        kickoff = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
        elapsed_min = (_utc_now() - kickoff).total_seconds() / 60
        return 0 <= elapsed_min <= _MAX_MATCH_MINUTES
    except Exception:
        return False


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
    matchday_nr ist None bei KO-Runden ohne Spieltag-Nummerierung oder wenn
    Spiele aus mehreren Matchdays zusammengefasst werden (z.B. WM-Gruppenphase).
    """
    group_matches = [m for m in all_matches if m.get("matchday") is not None]
    if group_matches:
        now = _utc_now()
        today_str = now.strftime("%Y-%m-%d")

        # a) Echte Live-Spiele (API-Status IN_PLAY/PAUSED) → deren Spieltag
        for m in group_matches:
            if m.get("status") in _LIVE:
                day = m["matchday"]
                return day, [x for x in group_matches if x.get("matchday") == day]

        # b) Zeitbasiert wahrscheinlich live (Free-Tier-Fallback) → deren Spieltag
        for m in group_matches:
            if _infer_probably_live(m):
                day = m["matchday"]
                return day, [x for x in group_matches if x.get("matchday") == day]

        # c) Heute laufende oder geplante Spiele — können über mehrere Matchdays verteilt
        #    sein (WM-Format: mehrere Gruppen gleichzeitig aktiv).
        today_games = [m for m in group_matches if (m.get("utcDate") or "").startswith(today_str)]
        if today_games:
            days_today = {m["matchday"] for m in today_games}
            if len(days_today) == 1:
                day = next(iter(days_today))
                return day, [x for x in group_matches if x.get("matchday") == day]
            # Mehrere Matchdays heute → alle heutigen Spiele, matchday_nr=None
            return None, sorted(today_games, key=lambda m: m.get("utcDate") or "")

        # d) Nächstes geplantes Spiel (frühestes Datum in der Zukunft, beliebiger Spieltag)
        upcoming = [m for m in group_matches if m.get("status") in {"SCHEDULED", "TIMED"}]
        if upcoming:
            upcoming.sort(key=lambda x: x.get("utcDate") or "")
            day = upcoming[0]["matchday"]
            return day, [x for x in group_matches if x.get("matchday") == day]

        # e) Gruppenphase abgeschlossen → KO-Runde bevorzugen wenn aktiv/anstehend
        ko_matches = [m for m in all_matches if m.get("matchday") is None]
        ko_active = [m for m in ko_matches if m.get("status") in _ACTIVE]
        if not ko_active:
            # Wichtig: "keine aktive KO-Runde" heißt nicht zwangsläufig "KO-Runde
            # hat noch nicht begonnen" — sie kann auch (inkl. Finale) bereits
            # komplett beendet sein. Dann muss die letzte beendete KO-Stage
            # gezeigt werden, sonst fällt die Anzeige nach Turnierende fälschlich
            # auf den letzten Gruppenspieltag zurück.
            ko_finished = [m for m in ko_matches if m.get("status") in _DONE]
            if ko_finished:
                ko_finished.sort(key=lambda x: x.get("utcDate") or "")
                last_stage = ko_finished[-1].get("stage")
                return None, [x for x in ko_matches if x.get("stage") == last_stage]
            finished = [m for m in group_matches if m.get("status") in _DONE]
            if finished:
                finished.sort(key=lambda x: x.get("utcDate") or "")
                day = finished[-1]["matchday"]
                return day, [x for x in group_matches if x.get("matchday") == day]
            return None, group_matches  # Fallback: alles
        # KO-Runde ist aktiv → Fall-through zur KO-Logik

    # KO-Phase (kein matchday oder Fall-through nach Gruppenphase): aktive Stage finden
    stages_order: list[str] = []
    for m in all_matches:
        s = m.get("stage") or ""
        if s and s not in stages_order:
            stages_order.append(s)

    for stage in stages_order:
        stage_matches = [m for m in all_matches if m.get("stage") == stage]
        if any(m.get("status") in _ACTIVE for m in stage_matches):
            return None, stage_matches

    active_stage = stages_order[-1] if stages_order else None
    if active_stage:
        return None, [m for m in all_matches if m.get("stage") == active_stage]
    return None, []


STANDINGS_TTL = 300   # Tabelle ändert sich selten — 5 Min reichen
DETAIL_TTL    = 30    # Spieldetails (goals/bookings): alle 30s für zügige Tor-Anzeige
MAX_LIVE_DETAILS = 2  # max. Extra-API-Calls pro Refresh (Rate-Limit-Schutz)


class TournamentService:
    _cache: dict[str, Any] = {}
    _cache_ts: float = 0.0
    _cache_code: str = ""
    _standings_cache: dict[str, Any] = {}
    _standings_cache_ts: float = 0.0
    _standings_cache_code: str = ""
    # Match-Detail-Cache: match_id → (timestamp, detail_dict)
    _detail_cache: dict[int, tuple[float, dict[str, Any]]] = {}

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

    def _enrich_with_details(self, live_matches: list[dict[str, Any]], now: float) -> None:
        """Holt goals + bookings via /matches/{id} für die ersten Live-Spiele.

        Separate API-Calls werden gecacht (DETAIL_TTL) und auf MAX_LIVE_DETAILS
        begrenzt, damit das Rate-Limit von 10 req/min eingehalten wird.
        Danach: worldcup26.ir (WM) → OpenLigaDB (Fallback) für Score + Tore.
        """
        from app.services.openligadb_service import enrich_goals as _oldb_enrich
        from app.services.worldcup26_service import enrich_match as _wc26_enrich
        fetches = 0
        for m in live_matches:
            if fetches >= MAX_LIVE_DETAILS:
                break
            mid = m.get("id")
            if not mid:
                continue
            cached_ts, cached_detail = TournamentService._detail_cache.get(mid, (0.0, {}))
            if now - cached_ts < DETAIL_TTL:
                detail = cached_detail
            else:
                detail = self._fetch(f"/matches/{mid}") or {}
                TournamentService._detail_cache[mid] = (now, detail)
                fetches += 1
            if detail:
                m["goals"]    = detail.get("goals")    or m.get("goals")    or []
                m["bookings"] = detail.get("bookings") or m.get("bookings") or []
            # WM: worldcup26.ir als primäre Quelle (Score + Torschützen)
            if self.competition_code == "WC":
                _wc26_enrich(m)
            # Fallback: OpenLigaDB (Score wenn null, Tore wenn noch keine vorhanden)
            _oldb_enrich(m, self.competition_code)

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
        # Fallback für Free-Tier: zeitbasierte Heuristik wenn API kein IN_PLAY liefert
        if not live_matches:
            live_matches = [m for m in all_matches if _infer_probably_live(m)]

        # Spieldetails (goals/bookings) für Live-Spiele separat nachladen
        if live_matches:
            self._enrich_with_details(live_matches, now)

        # Aktuellen Spieltag aus Match-Daten ermitteln (robust, unabhängig vom API-Hint)
        matchday_nr, matchday_matches = _resolve_matchday(all_matches, api_hint)

        matchday_matches.sort(key=lambda m: m.get("utcDate") or "")

        stage_key = matchday_matches[0].get("stage") if (matchday_nr is None and matchday_matches) else None
        result: dict[str, Any] = {
            "live": live_matches,
            "matchday": matchday_matches,
            "matchday_nr": matchday_nr,
            "stage": stage_key,
            "stage_label": _STAGE_LABEL.get(stage_key or "", None),
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
