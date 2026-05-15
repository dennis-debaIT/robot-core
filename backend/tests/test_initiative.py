from datetime import datetime, timedelta, timezone

from app.brain.initiative import InitiativeEngine


def test_initiative_allows_known_person_after_quiet_period():
    engine = InitiativeEngine()
    last_conversation = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()

    result = engine.evaluate(
        person_name="Dennis",
        known_person=True,
        battery_level=80,
        last_conversation_at=last_conversation,
        initiative_last_suggested_at=None,
        quiet_minutes=5,
        critical_battery_threshold=20,
        greeting_suggestion_template="Begrüßung für {person_name}",
    )

    assert result["allowed"] is True
    assert result["suggestion"] == "Begrüßung für Dennis"


def test_initiative_blocks_recent_conversation():
    engine = InitiativeEngine()
    last_conversation = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()

    result = engine.evaluate(
        person_name="Dennis",
        known_person=True,
        battery_level=80,
        last_conversation_at=last_conversation,
        initiative_last_suggested_at=None,
        quiet_minutes=5,
        critical_battery_threshold=20,
        greeting_suggestion_template="Begrüßung für {person_name}",
    )

    assert result == {"allowed": False, "reason": "recent_conversation"}
