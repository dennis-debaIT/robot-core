from app.profile.service import PersonProfileService


def test_single_value_traits_replace_previous_value(temp_db):
    service = PersonProfileService()

    service.upsert_fact(
        person_name="Dennis",
        trait_type="person_profile",
        value="Dennis",
        source_memory_id=1,
        confidence=0.98,
    )
    updated = service.upsert_fact(
        person_name="Dennis",
        trait_type="person_profile",
        value="Denny",
        source_memory_id=2,
        confidence=0.99,
    )

    facts = [fact for fact in updated["facts"] if fact["trait_type"] == "person_profile"]
    assert len(facts) == 1
    assert facts[0]["value"] == "Denny"


def test_multi_value_traits_keep_distinct_entries(temp_db):
    service = PersonProfileService()

    service.upsert_fact(
        person_name="Dennis",
        trait_type="preference",
        value="Kaffee",
        source_memory_id=1,
        confidence=0.93,
    )
    updated = service.upsert_fact(
        person_name="Dennis",
        trait_type="preference",
        value="Jazz",
        source_memory_id=2,
        confidence=0.91,
    )

    values = [fact["value"] for fact in updated["facts"] if fact["trait_type"] == "preference"]
    assert values == ["Jazz", "Kaffee"]


def test_response_preferences_are_single_value_and_readable(temp_db):
    service = PersonProfileService()

    service.upsert_fact(
        person_name="Dennis",
        trait_type="response_style_preference",
        value="locker",
        source_memory_id=None,
        confidence=1.0,
    )
    service.upsert_fact(
        person_name="Dennis",
        trait_type="response_humor_preference",
        value="higher",
        source_memory_id=None,
        confidence=1.0,
    )
    service.upsert_fact(
        person_name="Dennis",
        trait_type="response_style_preference",
        value="sachlich",
        source_memory_id=None,
        confidence=1.0,
    )

    preferences = service.get_response_preferences("Dennis")

    assert preferences == {
        "response_humor_preference": "higher",
        "response_style_preference": "sachlich",
    }
