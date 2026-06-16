from __future__ import annotations

import json
import time
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

BASE_URL = "https://api.football-data.org/v4"
CACHE_TTL = 55  # etwas unter 60s damit wir die 10 req/min-Grenze sicher einhalten


class TournamentService:
    _cache: dict[str, Any] = {}
    _cache_ts: float = 0.0
    _cache_code: str = ""

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
        current_matchday: int | None = competition.get("currentMatchday")

        live_statuses = {"IN_PLAY", "PAUSED"}
        live_matches = [m for m in all_matches if m.get("status") in live_statuses]

        # Spieltag-Ansicht: zeige Spiele des aktuellen Spieltags; falls KO-Phase,
        # zeige die Spiele der aktuellen Runde (Stage).
        if current_matchday is not None:
            matchday_matches = [m for m in all_matches if m.get("matchday") == current_matchday]
        else:
            # KO-Phase: neueste Stage nehmen (letzter SCHEDULED/FINISHED-Status)
            stages_seen: list[str] = []
            for m in all_matches:
                s = m.get("stage", "")
                if s and s not in stages_seen:
                    stages_seen.append(s)
            active_stage = stages_seen[-1] if stages_seen else None
            matchday_matches = [m for m in all_matches if m.get("stage") == active_stage] if active_stage else []

        # Spiele nach UTC-Datum sortieren, heutige und bevorstehende zuerst
        def _sort_key(m: dict[str, Any]) -> str:
            return m.get("utcDate") or ""

        matchday_matches.sort(key=_sort_key)

        result: dict[str, Any] = {
            "live": live_matches,
            "matchday": matchday_matches,
            "matchday_nr": current_matchday,
            "competition_name": competition.get("name", "Turnier"),
        }
        TournamentService._cache = result
        TournamentService._cache_ts = now
        TournamentService._cache_code = self.competition_code
        return result

    @classmethod
    def invalidate_cache(cls) -> None:
        cls._cache = {}
        cls._cache_ts = 0.0
