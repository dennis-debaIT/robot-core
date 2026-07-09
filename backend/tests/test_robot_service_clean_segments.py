import pytest

from app.services.robot_service import RobotService


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("app.services.robot_service.time.sleep", lambda *_: None)


class FakeHA:
    def __init__(self, states):
        self._states = states
        self.calls = []

    def get_states(self):
        return self._states

    def call_service(self, domain, service, data):
        self.calls.append((domain, service, dict(data)))
        return True


def _state(entity_id, state="unknown", options=None):
    attrs = {"options": options} if options is not None else {}
    return {"entity_id": entity_id, "state": state, "attributes": attrs}


def test_clean_segments_disables_cleangenius_before_setting_mode():
    ha = FakeHA([
        _state("sensor.krumel_knecht_battery_level", "99"),
        _state("select.krumel_knecht_cleangenius", "routine_cleaning", ["off", "routine_cleaning", "deep_cleaning"]),
        _state("select.krumel_knecht_cleaning_mode", "sweeping", ["sweeping", "mopping", "sweeping_and_mopping"]),
    ])
    svc = RobotService(ha=ha)

    svc.clean_segments({
        "entity_id": "vacuum.krumel_knecht",
        "segments": [3, 4],
        "cleaning_mode_option": "sweeping_and_mopping",
    })

    select_calls = [c for c in ha.calls if c[0] == "select"]
    assert select_calls[0] == ("select", "select_option", {"entity_id": "select.krumel_knecht_cleangenius", "option": "off"})
    assert select_calls[1] == ("select", "select_option", {"entity_id": "select.krumel_knecht_cleaning_mode", "option": "sweeping_and_mopping"})

    clean_calls = [c for c in ha.calls if c[0] == "dreame_vacuum"]
    assert clean_calls == [("dreame_vacuum", "vacuum_clean_segment", {"entity_id": "vacuum.krumel_knecht", "segments": [3, 4]})]


def test_clean_segments_skips_cleangenius_when_entity_absent():
    ha = FakeHA([
        _state("sensor.carsten_carsten_battery_level", "80"),
        _state("select.carsten_carsten_cleaning_mode", "sweeping", ["sweeping", "mopping"]),
    ])
    svc = RobotService(ha=ha)

    svc.clean_segments({
        "entity_id": "vacuum.carsten_carsten",
        "segments": [1],
        "cleaning_mode_option": "mopping",
    })

    select_calls = [c for c in ha.calls if c[0] == "select"]
    assert select_calls == [("select", "select_option", {"entity_id": "select.carsten_carsten_cleaning_mode", "option": "mopping"})]


def test_clean_segments_without_mode_option_skips_both_selects():
    ha = FakeHA([
        _state("sensor.krumel_knecht_battery_level", "99"),
        _state("select.krumel_knecht_cleangenius", "off", ["off", "routine_cleaning"]),
    ])
    svc = RobotService(ha=ha)

    svc.clean_segments({
        "entity_id": "vacuum.krumel_knecht",
        "segments": [5],
    })

    assert not any(c[0] == "select" for c in ha.calls)
    assert any(c[0] == "dreame_vacuum" for c in ha.calls)
