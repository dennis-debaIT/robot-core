from app.profile.relationship import PersonRelationshipService
from app.profile.service import PersonProfileService


def test_negative_interactions_raise_tension_and_lower_warmth(temp_db):
    profiles = PersonProfileService()
    person = profiles.ensure_person_stub("Dennis")
    service = PersonRelationshipService()

    result = service.apply_user_message(person_id=person["id"], message="Du nervst. Das ist echt blöd und scheiße.")

    assert result["person_state"]["tension"] > 0.2
    assert result["person_state"]["warmth"] < 0.0


def test_positive_interactions_raise_warmth(temp_db):
    profiles = PersonProfileService()
    person = profiles.ensure_person_stub("Christin")
    service = PersonRelationshipService()

    result = service.apply_user_message(person_id=person["id"], message="Danke, das war super und echt nett.")

    assert result["person_state"]["warmth"] > 0.0
    assert result["person_state"]["tension"] < 0.1
