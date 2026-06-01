"""
SearchService — Orchestrator für alle Such-Provider.

Routing-Logik:
  1. FootballProvider  → strukturierte Daten aus OpenLigaDB (Bundesliga/3. Liga)
  2. WeatherProvider   → Open-Meteo (aktuelles Wetter, kein API-Key)
  3. WebProvider       → DuckDuckGo (allgemeiner Fallback)

Stabile Fakten (historische Daten) werden als Memory-Kandidaten markiert.
Flüchtige Fakten (Sport, Wetter, News) werden nur für die aktuelle Antwort genutzt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.search.providers.football import FootballProvider
from app.search.providers.homeassistant import HomeAssistantProvider
from app.search.providers.weather import WeatherProvider
from app.search.providers.web import WebProvider
from app.search.providers.wikipedia import WikipediaProvider


@dataclass
class SearchResult:
    query: str
    snippet: str
    title: str
    url: str
    is_stable: bool
    memory_content: str | None
    meta: dict | None = None


class SearchService:
    # ── Suche überhaupt nötig? ───────────────────────────────────────────────

    _NEEDS_SEARCH_PATTERNS: list[re.Pattern[str]] = [
        re.compile(
            r"\b(letzt(?:es?|en?|er?|em?)\s+(?:spiel|partie|match|begegnung|spieltag)"
            r"|tabellenplatz|tabelle\s+(?:von|der|des)|punktestand"
            r"|hat\s+gewonnen|haben\s+gewonnen|hat\s+verloren"
            r"|wer\s+hat\s+(?:heute|gestern|zuletzt)\s+(?:gewonnen|gespielt)"
            r"|wie\s+(?:hat|hatte|lief|war)\s+(?:das\s+)?(?:spiel|partie|match)"
            r"|wie\s+(?:hat|hatte)\s+.{3,30}\s+gespielt"
            r"|hat\s+.{3,25}\s+(?:gewonnen|verloren|gespielt|unentschieden)"
            r"|ergebnis\s+(?:von|des|der)|spielstand|bundesliga|champions.?league"
            r"|wie\s+(?:steht|läuft)\s+es\s+(?:mit|bei|für|um)"
            r"|aktuell(?:e|er|es|en)?\s+(?:stand|platz|rang|ergebnis)"
            r"|auf\s+(?:welchem|welchen)\s+platz"
            r"|(?:wie\s+viele?|wieviele?)\s+punkte\s+hat"
            r"|wer\s+(?:führt|ist)\s+(?:die\s+)?(?:tabelle|liga|bundesliga)"
            r"|(?:wer|welche[rs]?)\s+(?:ist|steht)\s+(?:auf\s+)?platz\s*\d"
            r"|3\.\s*liga|2\.\s*bundesliga|1\.\s*bundesliga)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\bwas\s+(?:war|passierte|geschah|ist\s+passiert)\s+am\s+\d"
            r"|\bwas\s+(?:war|ist)\s+am\s+\d+\.?\s*\w+\.?\s*\d{4}"
            r"|\bwann\s+(?:wurde|war|ist|hat)\s+.{3,40}\s+(?:gegründet|geboren|gestorben|erfunden|entdeckt|gebaut)\b"
            r"|\bwer\s+(?:war|ist)\s+.{3,40}\s+\d{4}\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(wetter|temperatur|regen|schnee|wind|sonnig|bewölkt|nebel|gewitter"
            r"|wie\s+warm|wie\s+kalt|brauche\s+(?:schirm|jacke))\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(aktuelle[rns]?\s+news|was\s+(?:ist|passiert)\s+(?:gerade|aktuell|heute|gestern)"
            r"|was\s+(?:gibt\s+es\s+)?neues\s+(?:über|zu|bei|mit)"
            r"|heute\s+(?:passiert|gemeldet|bekannt|angekündigt))\b",
            re.IGNORECASE,
        ),
        # Faktenfragen: Wer/Was ist X, Wie alt/groß/hoch, Wann wurde X gegründet/geboren
        re.compile(
            r"\bwer\s+(?:ist|war|sind|waren)\s+(?!(?:du|ich|das|hier|da)\b).{2,50}"
            r"|\bwas\s+(?:ist|war|bedeutet|heißt)\s+(?!(?:du|dein|los|passiert|hier|da)\b).{2,50}"
            r"|\bwie\s+funktioniert\s+.{2,50}"
            r"|\bwie\s+(?:alt|groß|hoch|lang|weit)\s+ist\s+.{2,50}"
            r"|\bwann\s+(?:wurde|ist|hat)\s+.{2,40}\s+(?:geboren|gegründet|erfunden|gebaut|entdeckt|gestorben|erschienen)\b",
            re.IGNORECASE,
        ),
        # Explizite Info/Erklär-Anfragen
        re.compile(
            r"\b(?:erkläre?\s+(?:mir\s+)?|was\s+weißt\s+du\s+(?:über|zu|von)\s+"
            r"|erzähl\s+(?:mir\s+)?(?:etwas\s+)?(?:über|von)\s+"
            r"|informier(?:e|iere)\s+(?:mich\s+)?(?:über|zu)\s+)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:suche?\s+(?:mal\s+)?(?:im\s+internet|online|im\s+web|im\s+netz)"
            r"|schau\s+(?:mal\s+)?(?:im\s+internet|online|im\s+web|im\s+netz)"
            r"|guck\s+(?:mal\s+)?(?:im\s+internet|online)"
            r"|recherchiere?\s+(?:mal\s+)?(?:nach|zu|über|im\s+internet)?"
            r"|google\s+(?:mal|doch|das|nach)?"
            r"|such\s+(?:mal\s+)?(?:im\s+internet|online)"
            r"|im\s+internet\s+(?:suche?n?|nachschau|recherchier)"
            r"|schlag\s+(?:mal\s+)?nach)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(was\s+liegt\s+(heute|morgen)?\s*an"
            r"|liegt\s+(?:\w+\s+){0,5}an\b"
            r"|was\s+(?:haben\s+wir|passiert|ist|steht)\s+(?:heute|morgen|diese\s+woche)"
            r"|steht\s+(?:\w+\s+){0,5}an\b"
            r"|ansteh\w+"
            r"|(?:\w+\s+){0,3}(?:heute|morgen)\s+(?:\w+\s+){0,3}an\b"
            r"|anstehende?\s+termine?"
            r"|(?:meine\s+)?termine?(?:\s+(?:heute|morgen|diese\s+woche))?"
            r"|was\s+(?:gibt\s+es|gibt'?s|kommt)\s+(?:heute|morgen|diese\s+woche)"
            r"|nächste[rn]?\s+termin"
            r"|hab(?:e)?\s+ich\s+(?:heute|morgen)\s+(?:etwas|was|einen?\s+termin))\b",
            re.IGNORECASE,
        ),
    ]

    # ── Stabile Fakten (dauerhaft merkenswert) ───────────────────────────────

    _STABLE_PATTERNS: list[re.Pattern[str]] = [
        re.compile(r"\bwas\s+(?:war|passierte|geschah)\s+am\s+\d", re.IGNORECASE),
        re.compile(r"\bwann\s+(?:wurde|war)\s+.+\s+(?:geboren|gestorben|gegründet|erfunden|entdeckt)\b", re.IGNORECASE),
        re.compile(r"\bwer\s+(?:war|ist)\s+.+\s+\d{4}\b", re.IGNORECASE),
        re.compile(r"\d{1,2}\.\s*(?:januar|februar|märz|april|mai|juni|juli|august|september|oktober|november|dezember)\s+\d{4}", re.IGNORECASE),
    ]

    _VOLATILE_PATTERNS: list[re.Pattern[str]] = [
        re.compile(
            r"\b(letzt(?:es?|en?|er?)|aktuell|heute|gestern|diese\s+woche"
            r"|tabellenplatz|punktestand|spielstand|wetter|kurs|preis"
            r"|gerade|momentan|im\s+moment|derzeit)\b",
            re.IGNORECASE,
        ),
    ]

    _QUERY_CLEANUP = re.compile(
        r"^(?:kannst\s+du\s+mir\s+sagen[,\s]*"
        r"|weißt\s+du[,\s]*"
        r"|suche?\s+(?:im\s+internet|online|im\s+web|im\s+netz)(?:\s+(?:mal|doch|bitte))?\s+nach[,\s]*"
        r"|suche?\s+(?:mal\s+)?(?:im\s+internet|online|im\s+web|im\s+netz)(?:\s+danach)?\s*"
        r"|recherchiere?\s+(?:mal\s+)?(?:nach|zu|über)[,\s]*"
        r"|ich\s+würde\s+gern\s+wissen[,\s]*"
        r"|bitte\s+sag\s+mir[,\s]*"
        r"|sag\s+mir[,\s]*)",
        re.IGNORECASE,
    )

    # Verweisworte die alleine keinen Suchbegriff ergeben
    _REFERENCE_WORDS: frozenset[str] = frozenset({
        "danach", "das", "es", "davon", "dazu", "darüber", "daran",
        "darum", "dabei", "dadurch", "dafür", "dagegen", "damit",
        "darin", "darauf", "darunter", "daraus", "dem", "den",
        "dies", "dieses", "diesem", "diesen", "dessen",
    })

    def __init__(self) -> None:
        self._providers = [
            FootballProvider(),
            WeatherProvider(),
            HomeAssistantProvider(),  # Kalender-Anfragen via HA
            WikipediaProvider(),      # Faktenfragen (wer/was ist X)
            WebProvider(),            # immer letzter (Fallback)
        ]

    def needs_search(self, message: str) -> bool:
        return any(p.search(message) for p in self._NEEDS_SEARCH_PATTERNS)

    def is_stable_fact(self, message: str) -> bool:
        if any(p.search(message) for p in self._VOLATILE_PATTERNS):
            return False
        return any(p.search(message) for p in self._STABLE_PATTERNS)

    _QUERY_SUBJECT = re.compile(
        r"^(?:wer|was|wie|wann|welche[rs]?)\s+"
        r"(?:ist|war|sind|waren|bedeutet|heißt|funktioniert"
        r"|alt|groß|hoch|lang|weit|wurde|hat)\s+(?:der|die|das|ein|eine|der\s+|die\s+|das\s+)?",
        re.IGNORECASE,
    )

    def extract_query(self, message: str) -> str:
        cleaned = self._QUERY_CLEANUP.sub("", message.strip()).strip(" ,?!.")
        # Für Faktenfragen: Kernbegriff extrahieren (bessere DDG/Wikipedia-Treffer)
        core = self._QUERY_SUBJECT.sub("", cleaned).strip(" ,?!.")
        if core and len(core) >= 3 and len(core) < len(cleaned):
            return core
        return cleaned or message.strip()

    def is_reference_query(self, query: str) -> bool:
        """True wenn der extrahierte Suchbegriff nur ein Pronomen/Verweiswort ist."""
        return query.lower().strip(" ,?!.") in self._REFERENCE_WORDS or not query.strip()

    def search(self, query: str) -> SearchResult | None:
        stable = self.is_stable_fact(query)

        for provider in self._providers:
            if not provider.can_handle(query):
                continue
            raw = provider.search(query)
            if raw:
                memory_content = (
                    self._build_memory_content(query, raw["title"], raw["snippet"])
                    if stable else None
                )
                meta = {k: v for k, v in raw.items()
                        if k not in ("snippet", "title", "url", "is_stable")}
                return SearchResult(
                    query=query,
                    snippet=raw["snippet"],
                    title=raw["title"],
                    url=raw["url"],
                    is_stable=stable,
                    memory_content=memory_content,
                    meta=meta or None,
                )

        return None

    def format_prompt_block(self, result: SearchResult) -> str:
        source = "Wikipedia" if "wikipedia.org" in (result.url or "") else "Web-Recherche"
        kind = "stabiler Fakt" if result.is_stable else "aktuelle Information"
        return (
            f"[{source} — {kind}]: {result.snippet} "
            f"(Quelle: {result.title or result.url}) "
            f"Beantworte die Frage auf Basis dieser Information — fasse sie kurz und natürlich zusammen."
        )

    @staticmethod
    def _build_memory_content(query: str, title: str, snippet: str) -> str:
        short = snippet[:240].rsplit(" ", 1)[0] if len(snippet) > 240 else snippet
        if not short.endswith((".", "!", "?")):
            short += "."
        label = title if title else query
        return f"[Web-Recherche] {label}: {short}"
