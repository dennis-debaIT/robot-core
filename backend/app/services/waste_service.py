from __future__ import annotations

from datetime import date
from typing import Any

from app.search.providers.homeassistant import HomeAssistantProvider

DEFAULT_CALENDAR = "calendar.abfallkalender"

# Reihenfolge wichtig: erster Treffer im Titel gewinnt (break).
# (Schlüsselwörter im Event-Titel, Bilddatei in /assets/waste, Anzeige-Label)
_BIN_TYPES: list[tuple[tuple[str, ...], str, str]] = [
    (("gelb",),                        "yellow", "Gelbe Tonne"),
    (("braun", "bio"),                 "brown",  "Biotonne"),
    (("grün", "gruen"),                "green",  "Grüne Tonne"),
    (("blau", "papier"),               "blue",   "Papier"),
    (("grau", "schwarz", "restmüll", "rest"), "black", "Restmüll"),
]


class WasteService:
    def __init__(self, ha: HomeAssistantProvider | None = None) -> None:
        self.ha = ha or HomeAssistantProvider()

    def get_display_data(self, config: dict[str, Any]) -> dict[str, Any]:
        waste_cfg = config.get("waste") or {}
        entity = (waste_cfg.get("calendar_entity") or DEFAULT_CALENDAR).strip()

        # 6 Wochen Vorlauf — deckt auch 4-wöchentliche Tonnen sicher ab.
        events = self.ha.get_events_upcoming(days=42, selected_calendars=[entity])
        today = date.today()

        # Pro Farbe nur den nächsten (frühesten) zukünftigen Termin behalten —
        # über alle Varianten hinweg (14-täglich, 4-wöchentlich, verlegt …).
        best: dict[str, dict[str, Any]] = {}
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

            for keywords, image, label in _BIN_TYPES:
                if any(k in title for k in keywords):
                    if image not in best or days < best[image]["days"]:
                        best[image] = {
                            "color": image,
                            "label": label,
                            "date": dstr,
                            "days": days,
                        }
                    break

        bins = sorted(best.values(), key=lambda b: b["days"])
        return {"bins": bins, "entity": entity}
