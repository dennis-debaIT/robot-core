from __future__ import annotations

import concurrent.futures
import json
import pathlib
import re
import threading
import time
import unicodedata
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from app.services.tournament_service import (
    _resolve_matchday, _infer_probably_live, DETAIL_TTL, MAX_LIVE_DETAILS,
)

BASE_URL = "https://api.football-data.org/v4"

STATE_TTL      = 55   # Normal-Zustand
LIVE_STATE_TTL = 20   # Kürzere TTL wenn Live-Spiele laufen (Score-Updates ~alle 20s)
STANDINGS_TTL = 300   # Tabelle ändert sich selten
TEAMS_TTL     = 21600 # Team-Listen: 6h (ändert sich nur im Sommer)
FOCUS_TTL     = 55    # Team-Fokus In-Memory-TTL
FOCUS_DISK_TTL = 1800  # Team-Fokus Disk-Cache: 30 min
SQUAD_TTL     = 3600  # Kader: 1h

COMPETITION_NAMES: dict[str, str] = {
    "BL1": "1. Bundesliga",
    "BL2": "2. Bundesliga",
    "BL3": "3. Bundesliga",
}

_LIVE = {"IN_PLAY", "PAUSED"}


COMP_TEAMS_TTL = 3600      # WC/EC-Teamlisten: 1h
KADER_DISK_TTL = 7 * 86_400  # Stale-Schwelle: 7 Tage (Hintergrund-Refresh)

class LigaService:
    _state_cache:      dict[str, dict[str, Any]] = {}  # code → {data, ts}
    _standings_cache:  dict[str, dict[str, Any]] = {}
    _teams_cache:      dict[str, dict[str, Any]] = {}
    _focus_cache:      dict[str, dict[str, Any]] = {}  # str(team_id) → {data, ts}
    _squad_cache:      dict[str, dict[str, Any]] = {}  # str(team_id) → {data, ts}
    _comp_teams_cache: dict[str, dict[str, Any]] = {}  # comp_code → {data:{team_id: squad}, ts}
    # Match-Detail-Cache: match_id → (timestamp, detail_dict)
    _detail_cache: dict[int, tuple[float, dict[str, Any]]] = {}
    # Verhindert parallele Enrichment-Threads für denselben Verein
    _enriching_teams:  set[str] = set()
    _enriching_lock:   threading.Lock = threading.Lock()

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
            if cached:
                # Live-Spiele öfter aktualisieren — kürzere TTL für zügige Score-Updates
                ttl = LIVE_STATE_TTL if cached["data"].get("live") else STATE_TTL
                if (now - cached["ts"]) < ttl:
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

        # Disk-Cache — überlebt Container-Neustarts
        _focus_dir  = pathlib.Path("/data/tm_cache/focus")
        _focus_path = _focus_dir / f"{team_id}.json"
        if _focus_path.exists():
            try:
                disk = json.loads(_focus_path.read_text(encoding="utf-8"))
                age  = now - disk.get("ts", 0)
                if age < FOCUS_DISK_TTL:
                    LigaService._focus_cache[key] = {"data": disk["data"], "ts": now}
                    return disk["data"]
            except Exception:
                pass

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
                    "matchday_nr": m.get("matchday"),
                })

        # Fallback: OpenLigaDB für BL2/BL3-Teams (fd.o Free Tier gibt keinen Zugriff)
        if not last5:
            from app.services.openligadb_liga import get_team_last5 as _oldb_last5
            team_name_fb, fdorg_fb = "", ""
            for code, entry in LigaService._standings_cache.items():
                for row in ((entry.get("data") or {}).get("table") or []):
                    if (row.get("team") or {}).get("id") == team_id:
                        team_name_fb = (row["team"].get("name") or row["team"].get("shortName") or "")
                        fdorg_fb = code
                        break
                if team_name_fb:
                    break
            if team_name_fb and fdorg_fb:
                state_entry = LigaService._state_cache.get(fdorg_fb) or {}
                current_md = (state_entry.get("data") or {}).get("matchday_nr")
                last5 = _oldb_last5(fdorg_fb, team_name_fb, current_md)

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
        try:
            _focus_dir.mkdir(parents=True, exist_ok=True)
            _focus_path.write_text(
                json.dumps({"data": result, "ts": now}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass
        return result

    # ── Team-Kader (via /v4/teams/{id}) ──────────────────────────

    def _get_comp_squad(self, comp_code: str, team_id: int, now: float) -> list[dict[str, Any]]:
        """Sucht den Kader eines Teams in einem Wettkampf (z.B. WC, EC).

        Cached die gesamte Teamliste des Wettkampfs (1h), um API-Calls zu minimieren.
        """
        cached = LigaService._comp_teams_cache.get(comp_code)
        if cached and (now - cached["ts"]) < COMP_TEAMS_TTL:
            squads_by_id: dict[int, list] = cached["data"]
        else:
            data = self._fetch(f"/competitions/{comp_code}/teams")
            if not data:
                return []
            squads_by_id = {
                t["id"]: t.get("squad") or []
                for t in (data.get("teams") or [])
                if t.get("id")
            }
            LigaService._comp_teams_cache[comp_code] = {"data": squads_by_id, "ts": now}
        return squads_by_id.get(team_id) or []

    def get_team_squad(self, team_id: int) -> dict[str, Any] | None:
        """Kader eines Teams inkl. Trikotnummern — aus football-data.org /v4/teams/{id}.

        Fallback auf WC/EC-Teamliste wenn der direkte Endpoint keinen Kader liefert
        (passiert z.B. bei Kroatien, da fd.o Nationalkader nur in aktiven Turnieren populiert).
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

        # Fallback: WC- und EC-Teamlisten durchsuchen wenn Kader leer
        if not squad:
            for comp_code in ("WC", "EC", "CL", "EL"):
                squad = self._get_comp_squad(comp_code, team_id, now)
                if squad:
                    break

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
    _PERSON_CACHE_DIR = pathlib.Path("/data/tm_cache/persons")
    _PERSON_CHECK_INTERVAL = 24 * 3_600   # 24h bevor lastUpdated im Hintergrund geprüft wird
    _PERSON_MAX_TTL        = 30 * 86_400  # 30 Tage absolutes Maximum

    def get_person_profile(self, person_id: int) -> dict[str, Any] | None:
        """Erweitertes Spielerprofil — Disk-Cache, Invalidierung per lastUpdated."""
        now = time.time()
        key = f"person:{person_id}"
        # 1. In-Memory
        mem = LigaService._squad_cache.get(key)
        if mem and (now - mem["ts"]) < self._PERSON_CHECK_INTERVAL:
            return mem["data"]
        # 2. Disk-Cache
        cache_path = self._PERSON_CACHE_DIR / f"{person_id}.json"
        if cache_path.exists():
            try:
                entry = json.loads(cache_path.read_text(encoding="utf-8"))
                age = now - entry.get("ts", 0)
                result = entry["data"]
                LigaService._squad_cache[key] = {"data": result, "ts": now}
                if age < self._PERSON_CHECK_INTERVAL:
                    return result
                # CHECK_INTERVAL abgelaufen → Refresh im Hintergrund, sofort returnen
                def _bg(pid: int, path: pathlib.Path, old_lu: str | None, mem_key: str) -> None:
                    fresh_raw = self._fetch(f"/persons/{pid}")
                    if not fresh_raw:
                        try:
                            e = json.loads(path.read_text(encoding="utf-8"))
                            e["ts"] = time.time()
                            path.write_text(json.dumps(e, ensure_ascii=False), encoding="utf-8")
                        except Exception:
                            pass
                        return
                    new_lu = fresh_raw.get("lastUpdated")
                    if new_lu and new_lu == old_lu:
                        try:
                            e = json.loads(path.read_text(encoding="utf-8"))
                            e["ts"] = time.time()
                            path.write_text(json.dumps(e, ensure_ascii=False), encoding="utf-8")
                        except Exception:
                            pass
                        return
                    # Daten geändert → neu aufbauen und speichern
                    ct2 = fresh_raw.get("currentTeam") or {}
                    new_result: dict[str, Any] = {
                        "id":           fresh_raw.get("id"),
                        "name":         fresh_raw.get("name"),
                        "firstName":    fresh_raw.get("firstName"),
                        "lastName":     fresh_raw.get("lastName"),
                        "dateOfBirth":  fresh_raw.get("dateOfBirth"),
                        "nationality":  fresh_raw.get("nationality"),
                        "position":     fresh_raw.get("position"),
                        "shirtNumber":  fresh_raw.get("shirtNumber"),
                        "lastUpdated":  new_lu,
                        "currentTeam": {
                            "id": ct2.get("id"), "name": ct2.get("name"),
                            "shortName": ct2.get("shortName"), "tla": ct2.get("tla"),
                            "crest": ct2.get("crest"),
                            "contractUntil": (ct2.get("contract") or {}).get("until"),
                            "runningCompetitions": ct2.get("runningCompetitions") or [],
                        } if ct2 else None,
                    }
                    try:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(json.dumps({"data": new_result, "ts": time.time()}, ensure_ascii=False), encoding="utf-8")
                    except Exception:
                        pass
                    LigaService._squad_cache[mem_key] = {"data": new_result, "ts": time.time()}
                threading.Thread(target=_bg, args=(person_id, cache_path, entry.get("data", {}).get("lastUpdated"), key), daemon=True).start()
                return result
            except Exception:
                pass
        # 3. Kein Cache → synchron laden
        data = self._fetch(f"/persons/{person_id}")
        if not data:
            return None
        ct = data.get("currentTeam") or {}
        result = {
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
                "contractUntil":       (ct.get("contract") or {}).get("until"),
                "runningCompetitions": ct.get("runningCompetitions") or [],
            } if ct else None,
        }
        try:
            self._PERSON_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({"data": result, "ts": now}, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        LigaService._squad_cache[key] = {"data": result, "ts": now}
        return result

    # ── Vollständig angereicherter Kader (fd.o + TM, Disk-Cache) ──────────────

    @staticmethod
    def _kader_cache_path(team_name: str) -> pathlib.Path:
        """Cache-Pfad nur nach team_name (team_id im Schlüssel würde bei
        inkonsistenter Übergabe zu Cache-Misses führen)."""
        slug = re.sub(r"[^a-z0-9]", "_", team_name.strip().lower())[:80]
        return pathlib.Path("/data/tm_cache/kader") / f"{slug}.json"

    def get_full_kader(self, team_id: int | None, team_name: str) -> dict[str, Any]:
        """Kader sofort zurückgeben (Disk-Cache oder schnelle fd.o+TM-Liste).

        Stale-while-revalidate: Disk-Cache wird immer sofort serviert.
        Ist er älter als KADER_DISK_TTL (7 Tage), startet im Hintergrund
        ein vollständiger Rebuild (TM-Profil-Anreicherung) — die Antwort
        bleibt dabei nicht blockiert.
        Kein Cache: fd.o + TM-Liste schnell assembliert (1–3s), Anreicherung
        im Daemon-Thread.
        """
        from app.services.transfermarkt_service import TransfermarktService

        cache_dir  = pathlib.Path("/data/tm_cache/kader")
        cache_path = self._kader_cache_path(team_name)
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        # Stale-while-revalidate: vorhandenen Cache sofort zurückgeben
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if not (cached.get("squad") or []):
                    raise ValueError("leerer Kader-Cache, Live-Fetch erzwingen")
                age = time.time() - cache_path.stat().st_mtime
                # Re-Enrichment: a) Cache abgelaufen  b) Spieler mit TM-ID aber ohne Bild (API-Ratelimit beim letzten Lauf)
                squad = cached.get("squad") or []
                has_unenriched = any(
                    p.get("_tmId") and not p.get("imageURL") and not p.get("_tmProfileMissing")
                    for p in squad
                )
                if age > KADER_DISK_TTL or (has_unenriched and age > 120):
                    self._start_enrichment(team_id, team_name, cache_path)
                return cached
            except Exception:
                pass

        def _norm(n: str) -> str:
            n = unicodedata.normalize("NFKD", n or "").encode("ascii", "ignore").decode().lower()
            return re.sub(r"[^a-z]", "", n)

        tm_svc    = TransfermarktService()
        # fd.o-Squad + TM-Kaderliste parallel abrufen
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as fx:
            fdo_fut = fx.submit(self.get_team_squad, team_id) if team_id else None
            tm_fut  = fx.submit(tm_svc.get_club_players, team_name)
            fdo_data  = fdo_fut.result() if fdo_fut else None
            tm_raw    = tm_fut.result() or []
        fdo_squad = (fdo_data or {}).get("squad") or []

        tm_by_name = {_norm(p.get("name", "")): p for p in tm_raw}
        players: list[dict[str, Any]]
        if fdo_squad and tm_raw:
            players = []
            for fp in fdo_squad:
                tp = tm_by_name.get(_norm(fp.get("name", "")))
                p: dict[str, Any] = dict(fp)
                p["_tmId"]          = str(tp["id"]) if tp else None
                p["marketValue"]    = (tp or {}).get("marketValue")
                p["_source"]        = "fdo+tm" if tp else "fdo"
                p["_profileLoaded"] = False
                players.append(p)
        elif fdo_squad:
            players = [dict(p, _source="fdo", _tmId=None, _profileLoaded=False) for p in fdo_squad]
        else:
            players = [
                dict(p, _source="tm", _tmId=str(p.get("id", "") or ""), _profileLoaded=False)
                for p in tm_raw
            ]

        # Vollständige Anreicherung im Hintergrund — blockiert die Antwort nicht
        self._start_enrichment(team_id, team_name, cache_path)

        return {
            "id":        (fdo_data or {}).get("id"),
            "name":      (fdo_data or {}).get("name") or team_name,
            "shortName": (fdo_data or {}).get("shortName"),
            "tla":       (fdo_data or {}).get("tla"),
            "crest":     (fdo_data or {}).get("crest"),
            "squad":     players,
        }

    def _start_enrichment(
        self,
        team_id: int | None,
        team_name: str,
        cache_path: pathlib.Path,
    ) -> None:
        """Startet Enrichment-Thread nur wenn noch keiner für diesen Verein läuft."""
        key = team_name.lower().strip()
        with LigaService._enriching_lock:
            if key in LigaService._enriching_teams:
                return
            LigaService._enriching_teams.add(key)
        threading.Thread(
            target=self._enrich_and_cache_kader,
            args=(team_id, team_name, cache_path),
            daemon=True,
        ).start()

    def _enrich_and_cache_kader(
        self,
        team_id: int | None,
        team_name: str,
        cache_path: pathlib.Path,
    ) -> None:
        """Vollständiger Kader-Rebuild mit TM-Profil-Anreicherung + Disk-Write.
        Läuft im Daemon-Thread, blockiert keine HTTP-Antwort.
        """
        from app.services.transfermarkt_service import TransfermarktService

        def _norm(n: str) -> str:
            n = unicodedata.normalize("NFKD", n or "").encode("ascii", "ignore").decode().lower()
            return re.sub(r"[^a-z]", "", n)

        try:
            tm_svc = TransfermarktService()
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as fx:
                fdo_fut = fx.submit(self.get_team_squad, team_id) if team_id else None
                tm_fut  = fx.submit(tm_svc.get_club_players, team_name)
                fdo_data  = fdo_fut.result() if fdo_fut else None
                tm_raw    = tm_fut.result() or []
            fdo_squad = (fdo_data or {}).get("squad") or []

            tm_by_name = {_norm(p.get("name", "")): p for p in tm_raw}
            players: list[dict[str, Any]]
            if fdo_squad and tm_raw:
                players = []
                for fp in fdo_squad:
                    tp = tm_by_name.get(_norm(fp.get("name", "")))
                    p: dict[str, Any] = dict(fp)
                    p["_tmId"]          = str(tp["id"]) if tp else None
                    p["marketValue"]    = (tp or {}).get("marketValue")
                    p["_source"]        = "fdo+tm" if tp else "fdo"
                    p["_profileLoaded"] = False
                    players.append(p)
            elif fdo_squad:
                players = [dict(p, _source="fdo", _tmId=None, _profileLoaded=False) for p in fdo_squad]
            else:
                players = [
                    dict(p, _source="tm", _tmId=str(p.get("id", "") or ""), _profileLoaded=False)
                    for p in tm_raw
                ]

            def _enrich(p: dict) -> dict:
                try:
                    tm_id: str | None = p.get("_tmId")
                    if not tm_id and not p.get("_source", "").startswith("fdo"):
                        raw_id = p.get("id") or ""
                        if raw_id:
                            tm_id = str(raw_id)
                    if not tm_id and p.get("_source", "").startswith("fdo") and p.get("name"):
                        sr = tm_svc.search_player(p["name"])
                        if sr and sr.get("tm_id"):
                            tm_id            = sr["tm_id"]
                            p["_tmId"]       = tm_id
                            p["marketValue"] = sr.get("marketValue") or p.get("marketValue")
                            c = sr.get("club")
                            if c:
                                cn = c if isinstance(c, str) else (c or {}).get("name", "")
                                if cn:
                                    p["club"] = {**(p.get("club") or {}), "name": cn}
                            if sr.get("age"):
                                p["age"] = sr["age"]
                            if sr.get("nationalities"):
                                p["nationality"] = sr["nationalities"]
                    if tm_id:
                        prof = tm_svc.get_player_profile(str(tm_id))
                        if prof:
                            club = prof.get("club") or {}
                            # TM player profile enthält kein club.image → per club.id nachladen
                            if club.get("id") and not club.get("image"):
                                img = tm_svc.get_club_image_by_id(str(club["id"]))
                                if img:
                                    club = {**club, "image": img}
                            merged_club = {**(p.get("club") or {}), **{k: v for k, v in club.items() if v}}
                            # Längeren Clubnamen behalten — TM gibt oft Kurznamen (z.B. "Freiburg" statt "SC Freiburg")
                            orig_name = (p.get("club") or {}).get("name", "")
                            if orig_name and len(orig_name) > len(merged_club.get("name", "")):
                                merged_club["name"] = orig_name
                            prof_img = prof.get("imageUrl") or prof.get("imageURL") or prof.get("image")
                            if not prof_img:
                                # Profil erfolgreich geladen, aber kein Foto hinterlegt → kein Retry nötig
                                p["_tmProfileMissing"] = True
                            updates: dict[str, Any] = {
                                "imageURL":       prof_img,
                                "dateOfBirth":    prof.get("dateOfBirth") or p.get("dateOfBirth"),
                                "nationality":    prof.get("citizenship") or prof.get("nationality") or p.get("nationality"),
                                "height":         prof.get("height") or p.get("height"),
                                "weight":         prof.get("weight") or p.get("weight"),
                                "foot":           prof.get("foot") or p.get("foot"),
                                "placeOfBirth":   prof.get("placeOfBirth") or p.get("placeOfBirth"),
                                "joinedOn":       prof.get("joinedOn") or club.get("joined") or p.get("joinedOn"),
                                "signedFrom":     prof.get("signedFrom") or club.get("lastClubName") or p.get("signedFrom"),
                                "contractUntil":  prof.get("contractUntil") or club.get("contractExpires") or p.get("contractUntil"),
                                "contractOption": prof.get("contractOption") or club.get("contractOption") or p.get("contractOption"),
                                "marketValue":    prof.get("marketValue") or p.get("marketValue"),
                                "club":           merged_club if merged_club else p.get("club"),
                            }
                            if prof.get("age") is not None:
                                updates["age"] = prof["age"]
                            if prof.get("shirtNumber") is not None:
                                updates["shirtNumber"] = prof["shirtNumber"]
                            p.update({k: v for k, v in updates.items() if v is not None})
                except Exception:
                    pass
                # _profileLoaded = False nur wenn _tmId gesetzt, API-Call fehlgeschlagen und kein _tmProfileMissing
                # (→ wird beim nächsten Re-Enrichment-Zyklus erneut versucht)
                p["_profileLoaded"] = not (
                    p.get("_tmId") and not p.get("imageURL") and not p.get("_tmProfileMissing")
                )
                return p

            meta: dict[str, Any] = {
                "id":        (fdo_data or {}).get("id"),
                "name":      (fdo_data or {}).get("name") or team_name,
                "shortName": (fdo_data or {}).get("shortName"),
                "tla":       (fdo_data or {}).get("tla"),
                "crest":     (fdo_data or {}).get("crest"),
            }
            enriched_map: dict[int, dict[str, Any]] = {}

            def _write_partial() -> None:
                squad = [enriched_map.get(i, players[i]) for i in range(len(players))]
                try:
                    cache_path.write_text(
                        json.dumps({**meta, "squad": squad}, ensure_ascii=False),
                        encoding="utf-8",
                    )
                except Exception:
                    pass

            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
                futures = {ex.submit(_enrich, p): i for i, p in enumerate(players)}
                for fut in concurrent.futures.as_completed(futures):
                    idx = futures[fut]
                    try:
                        enriched_map[idx] = fut.result()
                    except Exception:
                        enriched_map[idx] = players[idx]
                    # Alle 2 fertigen Spieler progressiv in Cache schreiben
                    if len(enriched_map) % 2 == 0 or len(enriched_map) == len(players):
                        _write_partial()
        except Exception:
            pass
        finally:
            with LigaService._enriching_lock:
                LigaService._enriching_teams.discard(team_name.lower().strip())

    # ── Cache invalidieren ────────────────────────────────────────
    @classmethod
    def invalidate_cache(cls) -> None:
        cls._state_cache     = {}
        cls._standings_cache = {}
        cls._focus_cache     = {}
        # _teams_cache bewusst nicht leeren — 6h-TTL reicht
