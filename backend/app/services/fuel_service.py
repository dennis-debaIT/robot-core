from __future__ import annotations

import re
from typing import Any

from app.services.homeassistant_service import HomeAssistantService


class FuelService:
    _TYPE_OPTIONS = [
        {"id": "diesel", "label": "Diesel"},
        {"id": "e5", "label": "Super E5"},
        {"id": "e10", "label": "Super E10"},
        {"id": "super", "label": "Super"},
        {"id": "benzin", "label": "Benzin"},
        {"id": "lpg", "label": "LPG"},
        {"id": "adblue", "label": "AdBlue"},
    ]

    def __init__(self, ha: HomeAssistantService | None = None) -> None:
        self.ha = ha or HomeAssistantService()

    def type_options(self) -> list[dict[str, str]]:
        return list(self._TYPE_OPTIONS)

    def station_catalog(self) -> list[dict[str, Any]]:
        raw = self.ha.get_fuel_prices()
        if not raw:
            return []
        stations: dict[str, dict[str, Any]] = {}
        for entry in self._flatten_entries(raw):
            station_id = self._station_id(entry)
            type_id = self._detect_type_id(entry)
            station = stations.setdefault(
                station_id,
                {
                    "id": station_id,
                    "label": self._station_name(entry),
                    "entities": [],
                    "fuel_types": [],
                },
            )
            if type_id not in station["fuel_types"]:
                station["fuel_types"].append(type_id)
            station["entities"].append(
                {
                    "entity_id": entry.get("entity_id", ""),
                    "name": entry.get("name", ""),
                    "type_id": type_id,
                    "type_label": self._label_for(type_id),
                    "price": entry.get("price"),
                    "unit": entry.get("unit", ""),
                }
            )
        for station in stations.values():
            station["fuel_types"].sort(key=self._type_sort_key)
            station["entities"].sort(key=lambda item: self._type_sort_key(item["type_id"]))
        return sorted(stations.values(), key=lambda item: item["label"].lower())

    def get_display_data(self, config: dict[str, Any]) -> dict[str, Any] | None:
        fuel_config = config.get("fuel_prices", {})
        if not bool(fuel_config.get("enabled", True)):
            return None

        raw = self.ha.get_fuel_prices()
        if not raw:
            return None

        selected_types = self._sanitize_selected_types(fuel_config.get("fuel_types"))
        if not selected_types:
            return None
        selected_station_id = str(fuel_config.get("selected_station_id") or "").strip()
        assignments = fuel_config.get("fuel_assignments") if isinstance(fuel_config.get("fuel_assignments"), dict) else {}

        grouped: dict[str, list[dict[str, Any]]] = {}
        for entry in self._flatten_entries(raw):
            entry["_station_id"] = self._station_id(entry)
            entry["_station_name"] = self._station_name(entry)
            if selected_station_id and entry["_station_id"] != selected_station_id:
                continue
            type_id = self._detect_type_id(entry)
            grouped.setdefault(type_id, []).append(entry)

        entries_by_entity = {
            str(entry.get("entity_id") or ""): entry
            for entries in grouped.values()
            for entry in entries
            if entry.get("entity_id")
        }

        cards: list[dict[str, Any]] = []
        for type_id in selected_types:
            assigned_entity = str(assignments.get(type_id) or "").strip()
            if assigned_entity:
                assigned = entries_by_entity.get(assigned_entity)
                entries = [assigned] if assigned else []
            else:
                entries = sorted(grouped.get(type_id, []), key=lambda item: item.get("price", 99))
            if not entries:
                continue
            cards.append(
                {
                    "id": type_id,
                    "label": self._label_for(type_id),
                    "entity_id": entries[0].get("entity_id", ""),
                    "primary": entries[0],
                    "alternatives": entries[1:4],
                }
            )

        if not cards:
            return None

        station_name = cards[0]["primary"].get("_station_name") or self._station_name(cards[0]["primary"])

        return {
            "enabled": bool(fuel_config.get("enabled", True)),
            "selected_types": selected_types,
            "selected_station_id": selected_station_id,
            "cards": cards,
            "station_name": station_name,
            "updated_at": raw.get("updated_at"),
        }

    def _flatten_entries(self, raw: dict[str, Any]) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for items in (raw.get("grouped") or {}).values():
            if isinstance(items, list):
                entries.extend(item for item in items if isinstance(item, dict))
        return entries

    def _detect_type_id(self, entry: dict[str, Any]) -> str:
        haystack = " ".join(
            [str(entry.get("fuel_type", "")), str(entry.get("name", "")), str(entry.get("entity_id", ""))]
        ).lower()
        if "diesel" in haystack:
            return "diesel"
        if "e10" in haystack:
            return "e10"
        if "e5" in haystack:
            return "e5"
        if "lpg" in haystack or "autogas" in haystack:
            return "lpg"
        if "adblue" in haystack or "ad blue" in haystack:
            return "adblue"
        if "super" in haystack:
            return "super"
        if "benzin" in haystack:
            return "benzin"
        return "super"

    def _sanitize_selected_types(self, value: Any) -> list[str]:
        allowed = {item["id"] for item in self._TYPE_OPTIONS}
        if not isinstance(value, list):
            return ["diesel"]
        selected = [str(item) for item in value if str(item) in allowed]
        return selected

    def _label_for(self, type_id: str) -> str:
        for item in self._TYPE_OPTIONS:
            if item["id"] == type_id:
                return item["label"]
        return type_id.title()

    def _type_sort_key(self, type_id: str) -> int:
        order = [item["id"] for item in self._TYPE_OPTIONS]
        return order.index(type_id) if type_id in order else len(order)

    def _station_name(self, entry: dict[str, Any]) -> str:
        name = str(entry.get("name", "")).strip()
        if not name:
            return ""
        normalized = re.sub(
            r"\s+(diesel|super\s+e10|super\s+e5|super|e10|e5|benzin|lpg|autogas|adblue|ad\s+blue)\s*$",
            "",
            name,
            flags=re.IGNORECASE,
        )
        normalized = re.sub(r"\s{2,}", " ", normalized).strip(" -")
        return normalized or name

    def _station_id(self, entry: dict[str, Any]) -> str:
        station_name = self._station_name(entry).lower()
        station_name = re.sub(r"[^a-z0-9]+", "_", station_name)
        return station_name.strip("_") or "station"
