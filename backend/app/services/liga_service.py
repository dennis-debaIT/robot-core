from __future__ import annotations

import json
import time
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from app.services.tournament_service import (
    _resolve_matchday, _infer_probably_live, DETAIL_TTL, MAX_LIVE_DETAILS,
)

BASE_URL = "https://api.football-data.org/v4"

STATE_TTL     = 55    # Live-Daten — unter 60s damit Rate-Limit eingehalten wird
STANDINGS_TTL = 300   # Tabelle ändert sich selten
TEAMS_TTL     = 21600 # Team-Listen: 6h (ändert sich nur im Sommer)
FOCUS_TTL     = 55    # Team-Fokus: gleich wie Live-Daten
SQUAD_TTL     = 3600  # Kader: 1h

COMPETITION_NAMES: dict[str, str] = {
    "BL1": "1. Bundesliga",
    "BL2": "2. Bundesliga",
    "BL3": "3. Bundesliga",
}

_LIVE = {"IN_PLAY", "PAUSED"}


class LigaService:
    _state_cache:     dict[str, dict[str, Any]] = {}  # code → {data, ts}
    _standings_cache: dict[str, dict[str, Any]] = {}
    _teams_cache:     dict[str, dict[str, Any]] = {}
    _focus_cache:     dict[str, dict[str, Any]] = {}  # str(team_id) → {data, ts}
    _squad_cache:     dict[str, dict[str, Any]] = {}  # str(team_id) → {data, ts}
    # Match-Detail-Cache: match_id → (timestamp, detail_dict)
    _detail_cache: dict[int, tuple[float, dict[str, Any]]] = {}

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    # ── HTTP ──────────────────────────────────────────────────────
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

    def _enrich_with_details(self, live_matches: list[dict[str, Any]], now: float, code: str = "") -> None:
        """Holt goals + bookings via /matches/{id} für die ersten Live-Spiele.
        Fallback auf OpenLigaDB wenn football-data.org keine Tore liefert.
        """
        from app.services.openligadb_service import enrich_goals as _oldb_enrich
        fetches = 0
        for m in live_matches:
            if fetches >= MAX_LIVE_DETAILS:
                break
            mid = m.get("id")
            if not mid:
                continue
            cached_ts, cached_detail = LigaService._detail_cache.get(mid, (0.0, {}))
            if now - cached_ts < DETAIL_TTL:
                detail = cached_detail
            else:
                detail = self._fetch(f"/matches/{mid}") or {}
                LigaService._detail_cache[mid] = (now, detail)
                fetches += 1
            if detail:
                m["goals"]    = detail.get("goals")    or m.get("goals")    or []
                m["bookings"] = detail.get("bookings") or m.get("bookings") or []
            # Fallback: OpenLigaDB wenn football-data.org keine Tore liefert
            _oldb_enrich(m, code)

    # ── State (Spieltag + Live) ───────────────────────────────────
    def get_state(self, codes: list[str]) -> list[dict[str, Any]]:
        from app.services.openligadb_liga import get_state as _oldb_get_state
        now = time.time()
        result: list[dict[str, Any]] = []
        for code in codes:
            cached = LigaService._state_cache.get(code)
            if cached and (now - cached["ts"]) < STATE_TTL:
                result.append(cached["data"])
                continue

            data = self._fetch(f"/competitions/{code}/matches")
            if not data:
                # BL2/BL3 liefern 403 auf Free-Tier → OpenLigaDB als Fallback
                oldb = _oldb_get_state(code)
                if oldb:
                    LigaService._state_cache[code] = {"data": oldb, "ts": now}
                    result.append(oldb)
                elif cached:
                    result.append(cached["data"])
                continue

            all_matches: list[dict[str, Any]] = data.get("matches", [])
            competition: dict[str, Any]       = data.get("competition", {})

            api_hint: int | None = (
                competition.get("currentMatchday")
                or (competition.get("currentSeason") or {}).get("currentMatchday")
            )

            matchday_nr, matchday_matches = _resolve_matchday(all_matches, api_hint)
            matchday_matches.sort(key=lambda m: m.get("utcDate") or "")
            live = [m for m in matchday_matches if m.get("status") in _LIVE]
            if not live:
                live = [m for m in matchday_matches if _infer_probably_live(m)]

            # Spieldetails (goals/bookings) für Live-Spiele separat nachladen
            if live:
                self._enrich_with_details(live, now, code)

            league_data: dict[str, Any] = {
                "code": code,
                "name": COMPETITION_NAMES.get(code, competition.get("name", code)),
                "matchday_nr": matchday_nr,
                "matches": matchday_matches,
                "live": live,
            }
            LigaService._state_cache[code] = {"data": league_data, "ts": now}
            result.append(league_data)

        return result

    # ── Tabelle ───────────────────────────────────────────────────
    def get_standings(self, code: str) -> dict[str, Any]:
        from app.services.openligadb_liga import get_standings as _oldb_get_standings
        now = time.time()
        cached = LigaService._standings_cache.get(code)
        if cached and (now - cached["ts"]) < STANDINGS_TTL:
            return cached["data"]

        data = self._fetch(f"/competitions/{code}/standings")
        if not data:
            oldb = _oldb_get_standings(code)
            if oldb:
                LigaService._standings_cache[code] = {"data": oldb, "ts": now}
                return oldb
            return cached["data"] if cached else {"code": code, "table": [], "error": True}

        standings = data.get("standings", [])
        total = next(
            (s for s in standings if s.get("type") == "TOTAL" and not s.get("group")),
            None,
        )
        result: dict[str, Any] = {
            "code": code,
            "name": COMPETITION_NAMES.get(code, (data.get("competition") or {}).get("name", code)),
            "table": (total or {}).get("table", []),
        }
        LigaService._standings_cache[code] = {"data": result, "ts": now}
        return result

    # ── Teams (für Admin-Dropdown) ────────────────────────────────
    def get_teams(self, codes: list[str]) -> list[dict[str, Any]]:
        from app.services.openligadb_liga import get_teams as _oldb_get_teams
        now = time.time()
        all_teams: list[dict[str, Any]] = []
        for code in codes:
            cached = LigaService._teams_cache.get(code)
            if cached and (now - cached["ts"]) < TEAMS_TTL:
                all_teams.extend(cached["data"])
                continue

            data = self._fetch(f"/competitions/{code}/teams")
            if not data:
                oldb_teams = _oldb_get_teams(code)
                if oldb_teams:
                    LigaService._teams_cache[code] = {"data": oldb_teams, "ts": now}
                    all_teams.extend(oldb_teams)
                elif cached:
                    all_teams.extend(cached["data"])
                continue

            code_teams = [
                {
                    "id": t.get("id"),
                    "name": t.get("name"),
                    "shortName": t.get("shortName"),
                    "tla": t.get("tla"),
                    "league_code": code,
                    "league_name": COMPETITION_NAMES.get(code, code),
                }
                for t in data.get("teams", [])
            ]
            code_teams.sort(key=lambda t: t.get("name") or "")
            LigaService._teams_cache[code] = {"data": code_teams, "ts": now}
            all_teams.extend(code_teams)

        return sorted(all_teams, key=lambda t: (t.get("league_code", ""), t.get("name", "")))

    # ── Team-Fokus (letzte 5 + nächstes Spiel) ───────────────────
    def get_team_focus(self, team_id: int) -> dict[str, Any]:
        now = time.time()
        key = str(team_id)
        cached = LigaService._focus_cache.get(key)
        if cached and (now - cached["ts"]) < FOCUS_TTL:
            return cached["data"]

        # Letzte 5 abgeschlossene Spiele (ohne Competition-Filter — Free Tier erlaubt BL2/BL3 nicht)
        last5_raw = self._fetch(
            f"/teams/{team_id}/matches?status=FINISHED&limit=5"
        )
        last5: list[dict[str, Any]] = []
        if last5_raw:
            for m in last5_raw.get("matches", [])[-5:]:
                home   = m.get("homeTeam") or {}
                away   = m.get("awayTeam") or {}
                score  = (m.get("score") or {}).get("fullTime") or {}
                hg, ag = score.get("home"), score.get("away")
                is_home = home.get("id") == team_id
                if hg is not None and ag is not None:
                    if is_home:
                        r = "S" if hg > ag else ("U" if hg == ag else "N")
                    else:
                        r = "S" if ag > hg else ("U" if ag == hg else "N")
                else:
                    r = "?"
                last5.append({
                    "result": r,
                    "home": home.get("shortName") or home.get("name"),
                    "away": away.get("shortName") or away.get("name"),
                    "score": f"{hg}:{ag}" if hg is not None else "–",
                    "utcDate": m.get("utcDate"),
                })

        # Nächstes geplantes Spiel
        next_raw = self._fetch(
            f"/teams/{team_id}/matches?status=SCHEDULED,TIMED&limit=1"
        )
        next_match: dict[str, Any] | None = None
        if next_raw:
            matches = next_raw.get("matches") or []
            if matches:
                m = matches[0]
                next_match = {
                    "utcDate": m.get("utcDate"),
                    "home": (m.get("homeTeam") or {}).get("shortName"),
                    "away": (m.get("awayTeam") or {}).get("shortName"),
                    "competition": (m.get("competition") or {}).get("name"),
                }

        result: dict[str, Any] = {
            "team_id": team_id,
            "last5": last5,
            "next_match": next_match,
        }
        LigaService._focus_cache[key] = {"data": result, "ts": now}
        return result

    # ── Team-Kader (via /v4/teams/{id}) ──────────────────────────
    def get_team_squad(self, team_id: int) -> dict[str, Any] | None:
        """Kader eines Teams inkl. Trikotnummern — aus football-data.org /v4/teams/{id}.

        Funktioniert für Nationalmannschaften und Vereinsmannschaften gleichermaßen.
        """
        now = time.time()
        key = str(team_id)
        cached = LigaService._squad_cache.get(key)
        if cached and (now - cached["ts"]) < SQUAD_TTL:
            return cached["data"]

        data = self._fetch(f"/teams/{team_id}")
        if not data:
            return None
        squad = data.get("squad") or []
        result: dict[str, Any] = {
            "id":        data.get("id"),
            "name":      data.get("name"),
            "shortName": data.get("shortName"),
            "tla":       data.get("tla"),
            "crest":     data.get("crest"),
            "squad": [
                {
                    "id":          p.get("id"),
                    "name":        p.get("name"),
                    "position":    p.get("position"),
                    "dateOfBirth": p.get("dateOfBirth"),
                    "nationality": p.get("nationality"),
                    "shirtNumber": p.get("shirtNumber"),
                }
                for p in squad
            ],
        }
        if squad:
            LigaService._squad_cache[key] = {"data": result, "ts": now}
        return result

    # ── Spielerprofil (via /v4/persons/{id}) ─────────────────────
    def get_person_profile(self, person_id: int) -> dict[str, Any] | None:
        """Erweitertes Spielerprofil inkl. aktuellem Verein + Vertrag."""
        now = time.time()
        key = f"person:{person_id}"
        cached = LigaService._squad_cache.get(key)
        if cached and (now - cached["ts"]) < SQUAD_TTL:
            return cached["data"]

        data = self._fetch(f"/persons/{person_id}")
        if not data:
            return None

        ct = data.get("currentTeam") or {}
        result: dict[str, Any] = {
            "id":           data.get("id"),
            "name":         data.get("name"),
            "firstName":    data.get("firstName"),
            "lastName":     data.get("lastName"),
            "dateOfBirth":  data.get("dateOfBirth"),
            "nationality":  data.get("nationality"),
            "position":     data.get("position"),
            "shirtNumber":  data.get("shirtNumber"),
            "lastUpdated":  data.get("lastUpdated"),
            "currentTeam": {
                "id":          ct.get("id"),
                "name":        ct.get("name"),
                "shortName":   ct.get("shortName"),
                "tla":         ct.get("tla"),
                "crest":       ct.get("crest"),
                "contractUntil": (ct.get("contract") or {}).get("until"),
            } if ct else None,
        }
        LigaService._squad_cache[key] = {"data": result, "ts": now}
        return result

    # ── Cache invalidieren ────────────────────────────────────────
    @classmethod
    def invalidate_cache(cls) -> None:
        cls._state_cache     = {}
        cls._standings_cache = {}
        cls._focus_cache     = {}
        # _teams_cache bewusst nicht leeren — 6h-TTL reicht
