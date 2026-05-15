from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


class InitiativeEngine:
    def evaluate(
        self,
        *,
        person_name: str | None,
        known_person: bool,
        battery_level: int,
        last_conversation_at: str | None,
        initiative_last_suggested_at: str | None,
        quiet_minutes: int,
        critical_battery_threshold: int,
        greeting_suggestion_template: str,
    ) -> dict[str, Any]:
        if not person_name or not known_person:
            return {"allowed": False, "reason": "person_unknown"}
        if battery_level <= critical_battery_threshold:
            return {"allowed": False, "reason": "battery_critical"}

        now = datetime.now(timezone.utc)
        if initiative_last_suggested_at:
            last_suggested = datetime.fromisoformat(initiative_last_suggested_at)
            if now - last_suggested < timedelta(minutes=quiet_minutes):
                return {"allowed": False, "reason": "recently_suggested"}

        if last_conversation_at:
            last_conversation = datetime.fromisoformat(last_conversation_at)
            if now - last_conversation < timedelta(minutes=quiet_minutes):
                return {"allowed": False, "reason": "recent_conversation"}

        return {
            "allowed": True,
            "reason": "quiet_enough",
            "suggestion": greeting_suggestion_template.format(person_name=person_name),
        }
