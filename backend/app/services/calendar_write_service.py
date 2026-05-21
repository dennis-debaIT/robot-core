from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.homeassistant_service import HomeAssistantService
from app.services.integration_config_service import IntegrationConfigService


class CalendarWriteService:
    def __init__(self, ha: HomeAssistantService | None = None) -> None:
        self.ha = ha or HomeAssistantService()

    def default_write_entity(self) -> str:
        cfg = IntegrationConfigService().get_config()
        return str((cfg.get("calendar") or {}).get("default_write_entity") or "").strip()

    def write_entity_for_person(self, person_name: str | None) -> str | None:
        if not person_name:
            return None
        try:
            from app.profile.service import ProfileService
            svc = ProfileService()
            person = svc.get_person(person_name)
            if not person:
                return None
            for fact in person.get("facts") or []:
                if fact.get("trait_type") == "write_calendar_entity":
                    return str(fact["value"]).strip() or None
        except Exception:
            pass
        return None

    def resolve_entity(self, person_name: str | None) -> str | None:
        return self.write_entity_for_person(person_name) or self.default_write_entity() or None

    def create_event(
        self,
        entity_id: str,
        summary: str,
        start_dt: datetime,
        end_dt: datetime,
        description: str = "",
    ) -> bool:
        fmt = "%Y-%m-%d %H:%M:%S"
        data: dict[str, Any] = {
            "entity_id": entity_id,
            "summary": summary,
            "start_date_time": start_dt.strftime(fmt),
            "end_date_time": end_dt.strftime(fmt),
        }
        if description:
            data["description"] = description
        return self.ha.call_service("calendar", "create_event", data)

    @staticmethod
    def list_calendar_entities() -> list[dict[str, str]]:
        try:
            ha = HomeAssistantService()
            states = ha.get_states()
            return [
                {"entity_id": s["entity_id"], "name": (s.get("attributes") or {}).get("friendly_name", s["entity_id"])}
                for s in states
                if s.get("entity_id", "").startswith("calendar.")
            ]
        except Exception:
            return []
