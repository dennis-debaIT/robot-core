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


def test_clean_segments_applies_suction_and_water_level():
    ha = FakeHA([
        _state("sensor.krumel_knecht_battery_level", "99"),
        _state("select.krumel_knecht_cleaning_mode", "sweeping_and_mopping", ["sweeping_and_mopping"]),
        _state("select.krumel_knecht_suction_level", "standard", ["quiet", "standard", "strong", "turbo"]),
        _state("select.krumel_knecht_mop_pad_humidity", "moist", ["slightly_dry", "moist", "wet"]),
    ])
    svc = RobotService(ha=ha)

    svc.clean_segments({
        "entity_id": "vacuum.krumel_knecht",
        "segments": [6],
        "cleaning_mode_option": "sweeping_and_mopping",
        "suction_level": 2,   # -> "strong"
        "water_volume": 3,    # -> "wet"
    })

    select_calls = [c for c in ha.calls if c[0] == "select"]
    assert ("select", "select_option", {"entity_id": "select.krumel_knecht_suction_level", "option": "strong"}) in select_calls
    assert ("select", "select_option", {"entity_id": "select.krumel_knecht_mop_pad_humidity", "option": "wet"}) in select_calls


def test_clean_segments_water_volume_zero_is_not_sent():
    ha = FakeHA([
        _state("sensor.krumel_knecht_battery_level", "99"),
        _state("select.krumel_knecht_cleaning_mode", "sweeping", ["sweeping"]),
        _state("select.krumel_knecht_suction_level", "turbo", ["quiet", "standard", "strong", "turbo"]),
        _state("select.krumel_knecht_mop_pad_humidity", "moist", ["slightly_dry", "moist", "wet"]),
    ])
    svc = RobotService(ha=ha)

    svc.clean_segments({
        "entity_id": "vacuum.krumel_knecht",
        "segments": [3],
        "cleaning_mode_option": "sweeping",
        "suction_level": 3,   # -> "turbo"
        "water_volume": 0,    # -> kein Wasser, keine HA-Anfrage
    })

    select_calls = [c for c in ha.calls if c[0] == "select"]
    assert ("select", "select_option", {"entity_id": "select.krumel_knecht_suction_level", "option": "turbo"}) in select_calls
    assert not any(c[2].get("entity_id") == "select.krumel_knecht_mop_pad_humidity" for c in select_calls)


def test_clean_segments_skips_suction_water_when_entities_absent():
    ha = FakeHA([
        _state("sensor.carsten_carsten_battery_level", "80"),
        _state("select.carsten_carsten_cleaning_mode", "sweeping", ["sweeping"]),
    ])
    svc = RobotService(ha=ha)

    svc.clean_segments({
        "entity_id": "vacuum.carsten_carsten",
        "segments": [1],
        "cleaning_mode_option": "sweeping",
        "suction_level": 2,
        "water_volume": 2,
    })

    select_calls = [c for c in ha.calls if c[0] == "select"]
    assert select_calls == [("select", "select_option", {"entity_id": "select.carsten_carsten_cleaning_mode", "option": "sweeping"})]
