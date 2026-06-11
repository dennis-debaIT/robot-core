from __future__ import annotations

from datetime import date
from typing import Any

from app.search.providers.homeassistant import HomeAssistantProvider

DEFAULT_CALENDAR = "calendar.abfallkalender"

# Fallback wenn keine Tonnen konfiguriert sind (match-Keyword, label, Bilddatei).
_DEFAULT_BINS = [
    {"match": "gelb",  "label": "Gelbe Tonne", "color": "yellow"},
    {"match": "braun", "label": "Biotonne",    "color": "brown"},
    {"match": "grau",  "label": "Restmüll",    "color": "black"},
    {"match": "grün",  "label": "Grüne Tonne", "color": "green"},
]


class WasteService:
    def __init__(self, ha: HomeAssistantProvider | None = None) -> None:
        self.ha = ha or HomeAssistantProvider()

    def get_display_data(self, config: dict[str, Any]) -> dict[str, Any]:
        waste_cfg = config.get("waste") or {}
        entity = (waste_cfg.get("calendar_entity") or DEFAULT_CALENDAR).strip()
        bins_cfg = waste_cfg.get("bins") or _DEFAULT_BINS

        # 6 Wochen Vorlauf — deckt auch 4-wöchentliche Tonnen sicher ab.
        events = self.ha.get_events_upcoming(days=42, selected_calendars=[entity])
        today = date.today()

        # Pro konfigurierter Tonne nur den nächsten (frühesten) zukünftigen Termin —
        # über alle Varianten hinweg (14-täglich, 4-wöchentlich, verlegt …).
        # Index = Position in bins_cfg, damit zwei Regeln mit gleicher Farbe getrennt bleiben.
        best: dict[int, dict[str, Any]] = {}
        for ev in events:
            title = (ev.get("summary") or ev.get("title") or "").lower()
            start = ev.get("start") or {}
            dstr = start.get("date") or (start.get("dateTime", "")[:10])
            if not dstr:
                continue
            try:
                edate = date.fromisoformat(dstr)
            except ValueError:
                continue
            if edate < today:
                continue
            days = (edate - today).days

            for idx, rule in enumerate(bins_cfg):
                match = str(rule.get("match") or "").lower().strip()
                if match and match in title:
                    if idx not in best or days < best[idx]["days"]:
                        best[idx] = {
                            "color": rule.get("color") or "black",
                            "label": rule.get("label") or match,
                            "date": dstr,
                            "days": days,
                        }
                    break

        bins = sorted(best.values(), key=lambda b: b["days"])
        return {"bins": bins, "entity": entity}
