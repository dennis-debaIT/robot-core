"""
DuckDuckGo Provider — allgemeine Web-Suche als Fallback.

Für Anfragen die kein spezialisierter Provider abdeckt.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any


class WebProvider:
    """Allgemeine Web-Suche via DuckDuckGo. Greift immer als letzter Provider."""

    _RANK_PATTERN = re.compile(r"\b(\d{1,2})\.\s*(?:platz|rang)\b", re.IGNORECASE)
    _LEAGUE_PATTERN = re.compile(
        r"\b(1\.\s*bundesliga|2\.\s*bundesliga|3\.\s*liga|regionalliga"
        r"|premier\s*league|champions\s*league|europa\s*league"
        r"|serie\s*a|la\s*liga|ligue\s*1)\b",
        re.IGNORECASE,
    )
    _SEASON_PATTERN = re.compile(r"\b(20\d\d)[/-](20?\d\d)\b")

    def can_handle(self, query: str) -> bool:
        return True  # Immer als Fallback

    def search(self, query: str) -> dict[str, Any] | None:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return None

        current_year = str(datetime.now().year)
        prev_year = str(datetime.now().year - 1)

        queries = [
            f"{query} {current_year}",
            f"{query} aktuell {current_year}",
            query,
        ]

        all_results: list[dict] = []
        try:
            ddgs = DDGS()
            for q in queries:
                try:
                    raw = list(ddgs.text(q, region="de-de", safesearch="moderate", max_results=4))
                    all_results.extend(raw)
                    if len(all_results) >= 8:
                        break
                except Exception:
                    continue
        except Exception:
            return None

        if not all_results:
            return None

        # Deduplizieren
        seen: set[str] = set()
        unique = []
        for r in all_results:
            key = r.get("href") or r.get("url", "")
            if key not in seen:
                seen.add(key)
                unique.append(r)

        best = self._pick_best(unique, current_year=current_year, prev_year=prev_year)
        if not best:
            return None

        snippet = (best.get("body") or best.get("excerpt") or "").strip()
        if not snippet:
            return None

        confirmed: list[str] = []
        missing_rank = not self._RANK_PATTERN.search(snippet)
        league = self._LEAGUE_PATTERN.search(snippet) or self._LEAGUE_PATTERN.search(best.get("href", ""))
        season = self._SEASON_PATTERN.search(snippet) or self._SEASON_PATTERN.search(best.get("href", ""))

        if league:
            confirmed.append(f"Liga: {league.group(1)}")
        if season:
            confirmed.append(f"Saison: {season.group(1)}/{season.group(2)}")

        hint = ""
        if missing_rank and confirmed:
            hint = "HINWEIS: Genaue Platzierung nicht im Snippet — sage dem Nutzer das offen. "

        confirmed_str = f"Bestätigte Fakten: {' | '.join(confirmed)}. " if confirmed else ""
        return {
            "snippet": f"{hint}{confirmed_str}{snippet[:500]}",
            "title": best.get("title", ""),
            "url": best.get("href") or best.get("url", ""),
            "is_stable": False,
        }

    def _pick_best(
        self,
        results: list[dict],
        current_year: str = "",
        prev_year: str = "",
    ) -> dict | None:
        if not results:
            return None

        def text_of(r: dict) -> str:
            return (r.get("body") or r.get("excerpt") or "") + " " + (r.get("href") or "")

        def has_rank(r: dict) -> bool:
            return bool(self._RANK_PATTERN.search(text_of(r)))

        def has_league(r: dict) -> bool:
            return bool(self._LEAGUE_PATTERN.search(text_of(r)))

        def is_current(r: dict) -> bool:
            t = text_of(r)
            return bool(current_year and current_year in t) or bool(prev_year and prev_year in t)

        def body_len(r: dict) -> int:
            return len(r.get("body") or r.get("excerpt") or "")

        for r in results:
            if has_rank(r) and is_current(r) and body_len(r) > 40:
                return r
        for r in results:
            if has_league(r) and is_current(r) and body_len(r) > 40:
                return r
        for r in results:
            if is_current(r) and body_len(r) > 40:
                return r
        for r in results:
            if has_league(r) and body_len(r) > 40:
                return r
        for r in results:
            if body_len(r) > 40:
                return r
        return results[0]
