"""
Wikipedia Provider — deutsche Wikipedia-Zusammenfassungen für Faktenfragen.

Triggert bei "wer ist", "was ist", "was bedeutet", "wie funktioniert" etc.
Nutzt die öffentliche REST-API ohne API-Key.
"""
from __future__ import annotations

import re
import urllib.parse
import urllib.request
import json
from typing import Any


class WikipediaProvider:
    _TRIGGER = re.compile(
        r"\b(?:"
        r"wer\s+(?:ist|war|sind|waren)\s+"
        r"|was\s+(?:ist|war|sind|waren|bedeutet|heißt)\s+"
        r"|wie\s+funktioniert\s+"
        r"|wie\s+(?:alt|groß|hoch|lang|weit)\s+ist\s+"
        r"|wann\s+(?:wurde|ist|war|haben)\s+.{2,40}\s+(?:geboren|gegründet|erfunden|gebaut|entdeckt|gestorben|erschienen)"
        r"|was\s+(?:ist\s+der\s+unterschied|sind\s+die\s+unterschiede)\s+"
        r")\b",
        re.IGNORECASE,
    )

    # Diese Muster sollen NICHT Wikipedia auslösen (Fragen die Erika selbst beantworten kann)
    _SKIP = re.compile(
        r"\b(?:wer\s+(?:bist|sind)\s+du|was\s+(?:bist|kannst|machst|magst)\s+du"
        r"|wie\s+(?:heißt|alt)\s+du|dein\s+name|erika)\b",
        re.IGNORECASE,
    )

    # Extrahiert den Suchbegriff aus typischen Fragemuster
    _SUBJECT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
        (re.compile(r"\bwer\s+(?:ist|war|sind|waren)\s+(.+?)(?:\?|$)", re.IGNORECASE), r"\1"),
        (re.compile(r"\bwas\s+(?:ist|war|sind|waren|bedeutet|heißt)\s+(.+?)(?:\?|$)", re.IGNORECASE), r"\1"),
        (re.compile(r"\bwie\s+funktioniert\s+(.+?)(?:\?|$)", re.IGNORECASE), r"\1"),
        (re.compile(r"\bwie\s+(?:alt|groß|hoch|lang|weit)\s+ist\s+(.+?)(?:\?|$)", re.IGNORECASE), r"\1"),
        (re.compile(r"\bwann\s+wurde\s+(.+?)\s+(?:geboren|gegründet|erfunden|gebaut|entdeckt|gestorben|erschienen)", re.IGNORECASE), r"\1"),
    ]

    def can_handle(self, query: str) -> bool:
        if self._SKIP.search(query):
            return False
        return bool(self._TRIGGER.search(query))

    def search(self, query: str) -> dict[str, Any] | None:
        subject = self._extract_subject(query)
        if not subject or len(subject) < 2:
            return None

        # 1. Versuche direkte Seite über REST-Summary-API
        result = self._fetch_summary(subject)
        if result:
            return result

        # 2. Fallback: Suche via OpenSearch und dann Summary der ersten Treffern
        candidates = self._opensearch(subject)
        for candidate in candidates[:3]:
            result = self._fetch_summary(candidate)
            if result:
                return result

        return None

    def _extract_subject(self, query: str) -> str:
        for pattern, _ in self._SUBJECT_PATTERNS:
            m = pattern.search(query)
            if m:
                subject = m.group(1).strip().rstrip("?!.,")
                # Füllwörter am Ende entfernen
                subject = re.sub(r"\s+(?:eigentlich|denn|mal|bitte|doch|genau)\s*$", "", subject, flags=re.IGNORECASE)
                if subject:
                    return subject
        # Fallback: filler prefix wegschneiden
        cleaned = re.sub(
            r"^(?:wer|was|wie|wann|welche[rs]?)\s+(?:ist|war|sind|waren|bedeutet|heißt|funktioniert)\s+",
            "", query, flags=re.IGNORECASE,
        ).strip().rstrip("?!.,")
        return cleaned

    def _fetch_summary(self, title: str) -> dict[str, Any] | None:
        try:
            encoded = urllib.parse.quote(title.replace(" ", "_"))
            url = f"https://de.wikipedia.org/api/rest_v1/page/summary/{encoded}"
            req = urllib.request.Request(url, headers={"User-Agent": "ErikaRobot/1.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            extract = data.get("extract", "").strip()
            if not extract or data.get("type") == "disambiguation":
                return None
            page_title = data.get("title", title)
            # Zusammenfassung kürzen falls zu lang
            if len(extract) > 600:
                extract = extract[:600].rsplit(". ", 1)[0] + "."
            wiki_url = data.get("content_urls", {}).get("desktop", {}).get("page", "")
            return {
                "snippet": extract,
                "title": page_title,
                "url": wiki_url,
                "is_stable": True,
            }
        except Exception as exc:
            from app.audit.service import AuditService
            AuditService().log_warn(source="wikipedia", message=f"Wikipedia-Zusammenfassung fehlgeschlagen ({title}): {type(exc).__name__}: {exc}")
            return None

    def _opensearch(self, term: str) -> list[str]:
        try:
            encoded = urllib.parse.quote(term)
            url = f"https://de.wikipedia.org/w/api.php?action=opensearch&search={encoded}&limit=3&format=json"
            req = urllib.request.Request(url, headers={"User-Agent": "ErikaRobot/1.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data[1] if len(data) > 1 else []
        except Exception as exc:
            from app.audit.service import AuditService
            AuditService().log_warn(source="wikipedia", message=f"Wikipedia-Opensearch fehlgeschlagen ({term}): {type(exc).__name__}: {exc}")
            return []
