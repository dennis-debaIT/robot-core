from app.integrations.robot_core import RobotCore
from app.profile.service import PersonProfileService


def test_set_gender_updates_person_and_list(temp_db):
    svc = PersonProfileService()
    person_id = svc.ensure_person("Dennis")

    assert svc.get_person("Dennis")["gender"] is None

    updated = svc.set_gender(person_id, "m")
    assert updated["gender"] == "m"
    assert svc.get_person("Dennis")["gender"] == "m"

    by_id = next(p for p in svc.list_people() if p["id"] == person_id)
    assert by_id["gender"] == "m"

    cleared = svc.set_gender(person_id, None)
    assert cleared["gender"] is None


def test_set_gender_rejects_invalid_value(temp_db):
    svc = PersonProfileService()
    person_id = svc.ensure_person("Dennis")

    result = svc.set_gender(person_id, "invalid")
    assert result["gender"] is None


def test_set_gender_unknown_person_returns_none(temp_db):
    svc = PersonProfileService()
    assert svc.set_gender(999999, "m") is None


def test_chat_preview_includes_gender_hint_in_system_prompt(temp_db):
    svc = PersonProfileService()
    svc.set_gender(svc.ensure_person("Dennis"), "m")
    svc.set_gender(svc.ensure_person("Anna"), "w")
    svc.ensure_person("Unbestimmt")

    core = RobotCore()

    prompt_m = core.preview_chat_prompt("Hallo", person_name="Dennis")["system_prompt"]
    assert "Dennis" in prompt_m
    assert "männlich" in prompt_m
    assert "weiblich" not in prompt_m

    prompt_w = core.preview_chat_prompt("Hallo", person_name="Anna")["system_prompt"]
    assert "weiblich" in prompt_w

    prompt_none = core.preview_chat_prompt("Hallo", person_name="Unbestimmt")["system_prompt"]
    assert "männlich" not in prompt_none
    assert "weiblich" not in prompt_none
