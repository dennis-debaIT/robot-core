"""
OpenLigaDB Provider — strukturierte Fußballdaten für deutschen Profifußball.

Liefert Tabellenstände und Spielergebnisse aus 1. Bundesliga, 2. Bundesliga
und 3. Liga. Kein API-Key erforderlich.

API-Docs: https://api.openligadb.de
"""

from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Any


_TEAMS_CACHE_KEY = "football_teams_cache"
_TEAM_STOP_WORDS = {
    "der", "die", "das", "und", "von", "für", "aus", "bei", "dem", "den",
    "des", "ein", "eine", "rot", "blau", "wei", "spvgg",
}


class FootballProvider:
    BASE = "https://api.openligadb.de"

    LEAGUES = [
        ("bl1", "1. Bundesliga"),
        ("bl2", "2. Bundesliga"),
        ("bl3", "3. Liga"),
    ]

    # Erkennungsmuster für Fußball-Anfragen
    _PATTERN = re.compile(
        r"\b(tabellenplatz|tabellenstand|tabelle|bundesliga|2\.\s*bundesliga"
        r"|3\.\s*liga|spielergebnis|letztes\s+spiel|nächstes\s+spiel"
        r"|punktestand|liga\s+platz|wie\s+steht|wer\s+hat\s+gewonnen"
        r"|aufstieg|abstieg|meister|spieltag|fußball|fussball"
        r"|wie\s+hat.*gespielt|ergebnis|wie\s+(?:lief|war)\s+das\s+spiel"
        r"|torschütze|tore|gewonnen|verloren|unentschieden)\b",
        re.IGNORECASE,
    )

    _MATCH_RESULT_PATTERN = re.compile(
        r"\b(wie\s+hat|wie\s+(?:lief|war)|ergebnis|letztes?\s+spiel"
        r"|gespielt|gewonnen|verloren|unentschieden|tore|torschütze)\b",
        re.IGNORECASE,
    )

    def can_handle(self, query: str) -> bool:
        if self._PATTERN.search(query):
            return True
        # Auch handeln wenn ein bekannter Vereinsname im Query vorkommt
        team = self.detect_team_in_query(query)
        return team is not None

    def search(self, query: str) -> dict[str, Any] | None:
        """
        Gibt ein dict mit 'snippet', 'title', 'url', 'is_stable' zurück
        oder None wenn kein Treffer.
        """
        season_year = self._season_year()
        team_words = self._extract_team_words(query)

        # Spielergebnis-Anfragen zuerst versuchen
        if self._MATCH_RESULT_PATTERN.search(query):
            for league_id, league_name in self.LEAGUES:
                result = self._last_match_result(team_words, league_id, season_year, league_name)
                if result:
                    return result

        # Alle Ligen durchsuchen, ersten Treffer zurückgeben
        for league_id, league_name in self.LEAGUES:
            table = self._fetch_table(league_id, season_year)
            if not table:
                continue
            entry = self._match_team(table, team_words)
            if entry:
                rank = table.index(entry) + 1
                name = entry.get("teamName", "Unbekannt")
                points = entry.get("points", "?")
                wins = entry.get("won", entry.get("wins", "?"))
                draws = entry.get("draw", entry.get("draws", "?"))
                losses = entry.get("lost", entry.get("losses", "?"))
                goals = entry.get("goals", "?")
                opp = entry.get("opponentGoals", "?")
                snippet = (
                    f"{name} steht auf Platz {rank} in der "
                    f"{league_name} ({season_year}/{season_year + 1}). "
                    f"{points} Punkte, {wins} Siege, {draws} Unentschieden, {losses} Niederlagen. "
                    f"Tore: {goals}:{opp}."
                )
                return {
                    "snippet": snippet,
                    "title": f"{name} — {league_name} Tabelle",
                    "url": "https://www.openligadb.de/",
                    "is_stable": False,
                    "team_name": name,
                    "league_id": league_id,
                }

        # Kein Team gefunden — allgemeine Tabellenanfrage?
        league_id, league_name = self._detect_league(query)
        table = self._fetch_table(league_id, season_year)
        if table:
            lines = [
                f"Platz {i+1}: {e.get('teamName','?')} ({e.get('points','?')} Pkt., {e.get('wins','?')}S {e.get('draws','?')}U {e.get('losses','?')}N)"
                for i, e in enumerate(table[:18])
            ]
            snippet = (
                f"Aktuelle {league_name} Tabelle {season_year}/{season_year+1}: "
                + " | ".join(lines)
            )
            return {
                "snippet": snippet,
                "title": f"{league_name} Tabelle",
                "url": "https://www.openligadb.de/",
                "is_stable": False,
            }

        return None

    # ── Team-Cache ───────────────────────────────────────────────────────────

    @staticmethod
    def _team_keywords(name: str, short: str) -> list[str]:
        words = re.findall(r"[A-Za-zÄÖÜäöüß]{3,}", name + " " + short)
        return [w.lower() for w in words if w.lower() not in _TEAM_STOP_WORDS]

    def _load_teams_cache(self) -> dict | None:
        try:
            from app.database.db import get_connection, read_state
            with get_connection() as conn:
                raw = read_state(conn, _TEAMS_CACHE_KEY)
            if not raw or raw.get("season") != self._season_year():
                return None
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(raw["cached_at"])).days
            return raw.get("keywords") if age <= 7 else None
        except Exception:
            return None

    def _refresh_teams_cache(self) -> dict:
        season = self._season_year()
        keywords: dict[str, dict] = {}
        for league_id, league_name in self.LEAGUES:
            table = self._fetch_table(league_id, season)
            if not table:
                continue
            for entry in table:
                name = (entry.get("teamName") or "").strip()
                short = (entry.get("shortName") or "").strip()
                info = {"name": name, "short": short,
                        "league_id": league_id, "league_name": league_name}
                for kw in self._team_keywords(name, short):
                    # Längeres Keyword gewinnt (spezifischer)
                    if kw not in keywords or len(kw) > len(max(keywords, key=len, default="")):
                        keywords[kw] = info
        try:
            from app.database.db import get_connection, write_state
            with get_connection() as conn:
                write_state(conn, _TEAMS_CACHE_KEY, {
                    "season": season,
                    "cached_at": datetime.now(timezone.utc).isoformat(),
                    "keywords": keywords,
                })
        except Exception:
            pass
        return keywords

    def _get_teams(self) -> dict:
        return self._load_teams_cache() or self._refresh_teams_cache()

    def detect_team_in_query(self, query: str) -> dict | None:
        """Findet den am besten passenden Verein im Query via Team-Cache."""
        teams = self._get_teams()
        if not teams:
            return None
        q = query.lower()
        best: dict | None = None
        best_len = 0
        for kw, info in teams.items():
            if re.search(r"\b" + re.escape(kw) + r"\b", q) and len(kw) > best_len:
                best_len = len(kw)
                best = info
        return best

    # ── Interne Hilfsmethoden ────────────────────────────────────────────────

    @staticmethod
    def _season_year() -> int:
        """Aktuelles Saison-Startjahr (August-Juli-Zyklus)."""
        now = datetime.now()
        return now.year if now.month >= 8 else now.year - 1

    @staticmethod
    def _extract_team_words(query: str) -> list[str]:
        """Extrahiert bedeutsame Wörter für den Team-Abgleich."""
        stopwords = {
            "wie", "was", "wer", "wo", "wann", "auf", "ist", "sind", "hat",
            "haben", "steht", "stehen", "der", "die", "das", "den", "dem",
            "aktuell", "aktuelle", "aktueller", "gerade", "derzeit", "platz",
            "tabellenplatz", "liga", "bundesliga", "tabelle", "spieltag",
        }
        words = re.findall(r"[A-Za-zÄÖÜäöüß0-9]{2,}", query)
        return [w.lower() for w in words if w.lower() not in stopwords and len(w) >= 3]

    @staticmethod
    def _match_team(table: list[dict], query_words: list[str]) -> dict | None:
        """Findet das Team mit den meisten übereinstimmenden Wörtern."""
        best: dict | None = None
        best_score = 0
        for entry in table:
            name = (entry.get("teamName") or "").lower()
            short = (entry.get("shortName") or "").lower()
            combined = name + " " + short
            score = sum(1 for w in query_words if w in combined)
            if score > best_score:
                best_score = score
                best = entry
        return best if best_score > 0 else None

    def _detect_league(self, query: str) -> tuple[str, str]:
        """Erkennt welche Liga angefragt wird, Standard: 2. Bundesliga."""
        q = query.lower()
        if "1. bundesliga" in q or "erste bundesliga" in q or ("bundesliga" in q and "2." not in q and "3." not in q):
            return "bl1", "1. Bundesliga"
        if "3. liga" in q or "dritte liga" in q:
            return "bl3", "3. Liga"
        return "bl2", "2. Bundesliga"

    def _last_match_result(
        self, team_words: list[str], league_id: str, season_year: int, league_name: str
    ) -> dict[str, Any] | None:
        """Sucht das letzte abgeschlossene Spiel des Teams."""
        url = f"{self.BASE}/getmatchdata/{league_id}/{season_year}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "robot-core/0.2"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                matches = json.loads(resp.read().decode())
        except Exception:
            return None

        if not isinstance(matches, list):
            return None

        # Abgeschlossene Spiele des gesuchten Teams, neuestes zuerst
        finished = [
            m for m in matches
            if m.get("matchIsFinished")
            and (
                self._match_team(
                    [{"teamName": m.get("team1", {}).get("teamName", ""),
                      "shortName": m.get("team1", {}).get("shortName", "")}],
                    team_words,
                )
                or self._match_team(
                    [{"teamName": m.get("team2", {}).get("teamName", ""),
                      "shortName": m.get("team2", {}).get("shortName", "")}],
                    team_words,
                )
            )
        ]

        if not finished:
            return None

        # Letztes Spiel
        last = sorted(
            finished,
            key=lambda m: m.get("matchDateTimeUTC", ""),
            reverse=True,
        )[0]

        t1 = last.get("team1", {}).get("teamName", "?")
        t2 = last.get("team2", {}).get("teamName", "?")
        results = last.get("matchResults", [])
        # Endstand bevorzugen (resultTypeID 2), sonst erstes Ergebnis
        final = next((r for r in results if r.get("resultTypeID") == 2), results[0] if results else None)
        if not final:
            return None

        g1, g2 = final.get("pointsTeam1", "?"), final.get("pointsTeam2", "?")
        date_str = last.get("matchDateTimeUTC", "")[:10]

        # Halbzeitergebnis wenn vorhanden
        ht = next((r for r in results if r.get("resultTypeID") == 1), None)
        ht_str = f" (Halbzeit: {ht['pointsTeam1']}:{ht['pointsTeam2']})" if ht else ""

        snippet = (
            f"Letztes Spiel {t1} gegen {t2} am {date_str}: "
            f"Endstand {g1}:{g2}{ht_str}. Liga: {league_name}."
        )
        return {
            "snippet": snippet,
            "title": f"{t1} vs {t2} — {league_name}",
            "url": "https://www.openligadb.de/",
            "is_stable": False,
        }

    def get_team_display_data(self, team_name: str) -> dict[str, Any] | None:
        """
        Liefert strukturierte Anzeige-Daten für ein Team:
        - Letztes Spielergebnis mit Logo-URLs
        - Aktuelle Tabellenposition mit Umfeld (±2 Plätze)
        - Liga und Saison

        Wird vom /football/{team} Endpoint genutzt.
        """
        from datetime import datetime as _dt
        season_year = self._season_year()
        team_words = self._extract_team_words(team_name)

        for league_id, league_name in self.LEAGUES:
            table = self._fetch_table(league_id, season_year)
            if not table:
                continue
            entry = self._match_team(table, team_words)
            if not entry:
                continue

            rank = table.index(entry) + 1

            # Letztes Spiel
            last_match = self._fetch_last_match(team_words, league_id, season_year)

            # Vollständige Tabelle
            full_table = []
            for i, row in enumerate(table, start=1):
                full_table.append({
                    "rank": i,
                    "teamName": row.get("teamName", ""),
                    "shortName": row.get("shortName", ""),
                    "iconUrl": row.get("teamIconUrl", ""),
                    "points": row.get("points", 0),
                    "matches": row.get("matches", 0),
                    "wins": row.get("wins", 0),
                    "draws": row.get("draws", 0),
                    "losses": row.get("losses", 0),
                    "goals": row.get("goals", 0),
                    "opponentGoals": row.get("opponentGoals", 0),
                    "isHighlighted": i == rank,
                })

            return {
                "team": {
                    "name": entry.get("teamName", ""),
                    "shortName": entry.get("shortName", ""),
                    "iconUrl": entry.get("teamIconUrl", ""),
                },
                "league": {
                    "name": league_name,
                    "leagueId": league_id,
                    "season": f"{season_year}/{season_year + 1}",
                },
                "table": {
                    "rank": rank,
                    "points": entry.get("points", 0),
                    "matches": entry.get("matches", 0),
                    "wins": entry.get("wins", 0),
                    "draws": entry.get("draws", 0),
                    "losses": entry.get("losses", 0),
                    "goals": entry.get("goals", 0),
                    "opponentGoals": entry.get("opponentGoals", 0),
                    "goalDiff": entry.get("goals", 0) - entry.get("opponentGoals", 0),
                    "full_table": full_table,
                },
                "lastMatch": last_match,
                "updatedAt": _dt.utcnow().isoformat() + "Z",
            }

        return None

    def _fetch_last_match(
        self, team_words: list[str], league_id: str, season_year: int
    ) -> dict[str, Any] | None:
        url = f"{self.BASE}/getmatchdata/{league_id}/{season_year}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "robot-core/0.2"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                matches = json.loads(resp.read().decode())
        except Exception:
            return None

        if not isinstance(matches, list):
            return None

        finished = [
            m for m in matches
            if m.get("matchIsFinished")
            and (
                self._match_team([{
                    "teamName": m.get("team1", {}).get("teamName", ""),
                    "shortName": m.get("team1", {}).get("shortName", ""),
                }], team_words)
                or self._match_team([{
                    "teamName": m.get("team2", {}).get("teamName", ""),
                    "shortName": m.get("team2", {}).get("shortName", ""),
                }], team_words)
            )
        ]

        if not finished:
            return None

        last = sorted(finished, key=lambda m: m.get("matchDateTimeUTC", ""), reverse=True)[0]

        t1 = last.get("team1", {})
        t2 = last.get("team2", {})
        results = last.get("matchResults", [])
        final = next((r for r in results if r.get("resultTypeID") == 2), results[0] if results else None)
        ht = next((r for r in results if r.get("resultTypeID") == 1), None)

        if not final:
            return None

        g1 = final.get("pointsTeam1", 0)
        g2 = final.get("pointsTeam2", 0)

        # Prüfen ob gesuchtes Team Heim oder Gast war
        is_home = bool(self._match_team([{
            "teamName": t1.get("teamName", ""),
            "shortName": t1.get("shortName", ""),
        }], team_words))

        my_goals = g1 if is_home else g2
        opp_goals = g2 if is_home else g1

        if my_goals > opp_goals:
            result_label = "win"
            summary_verb = "gewonnen"
        elif my_goals < opp_goals:
            result_label = "defeat"
            summary_verb = "verloren"
        else:
            result_label = "draw"
            summary_verb = "unentschieden gespielt"

        my_name  = t1.get("teamName", "?") if is_home else t2.get("teamName", "?")
        opp_name = t2.get("teamName", "?") if is_home else t1.get("teamName", "?")
        short_opp = opp_name.split()[-1]
        summary = f"{my_name} hat zuletzt {my_goals}:{opp_goals} gegen {short_opp} {summary_verb}."

        return {
            "date": last.get("matchDateTimeUTC", "")[:10],
            "homeTeam": {
                "name": t1.get("teamName", ""),
                "shortName": t1.get("shortName", ""),
                "iconUrl": t1.get("teamIconUrl", ""),
                "score": g1,
            },
            "awayTeam": {
                "name": t2.get("teamName", ""),
                "shortName": t2.get("shortName", ""),
                "iconUrl": t2.get("teamIconUrl", ""),
                "score": g2,
            },
            "halfTime": {"home": ht["pointsTeam1"], "away": ht["pointsTeam2"]} if ht else None,
            "isHome": is_home,
            "result": result_label,
            "summary": summary,
        }

    def _fetch_table(self, league_id: str, season_year: int) -> list[dict] | None:
        url = f"{self.BASE}/getbltable/{league_id}/{season_year}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "robot-core/0.2"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode())
                return data if isinstance(data, list) else None
        except Exception:
            return None
