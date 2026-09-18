from app.database.db import get_connection
from app.services.robot_service import RobotService


def test_resolve_state_falls_back_to_english_error_sensor():
    """Regression: Krümel Knechts Fehler-Sensor heißt sensor.krumel_knecht_error
    (englisch), nicht sensor.<slug>_fehler (deutsch) wie bei den Mährobotern —
    _resolve_state() muss beide Varianten berücksichtigen."""
    svc = RobotService.__new__(RobotService)  # reine Logik-Methode, kein HA nötig
    extras = {"error": {"state": "dust_bag_full", "last_changed": "2026-01-01T00:00:00+00:00"}}
    result = svc._resolve_state("vacuum.krumel_knecht", "cleaning", extras, config=None)
    assert result == "error"


def test_resolve_state_prefers_fehler_key_when_both_present():
    svc = RobotService.__new__(RobotService)
    extras = {
        "fehler": {"state": "trapped", "last_changed": "2026-01-01T00:00:00+00:00"},
        "error": {"state": "no_error", "last_changed": "2026-01-01T00:00:00+00:00"},
    }
    result = svc._resolve_state("lawn_mower.robert", "mowing", extras, config=None)
    assert result == "error"  # "trapped" ist ein Default-critical_state


def test_resolve_state_no_error_extra_falls_back_to_base_state():
    svc = RobotService.__new__(RobotService)
    result = svc._resolve_state("vacuum.krumel_knecht", "cleaning", {}, config=None)
    assert result == "cleaning"


def test_resolve_state_no_error_value_is_not_flagged():
    """sensor.krumel_knecht_error meldet im Normalfall 'no_error' — das
    darf nicht als Fehlerzustand durchgereicht werden."""
    svc = RobotService.__new__(RobotService)
    extras = {"error": {"state": "no_error", "last_changed": "2026-01-01T00:00:00+00:00"}}
    result = svc._resolve_state("vacuum.krumel_knecht", "cleaning", extras, config=None)
    assert result == "cleaning"


def test_record_current_errors_uses_error_key_when_fehler_absent(temp_db):
    svc = RobotService()
    extras = {"error": {"state": "battery_low", "last_changed": "2026-01-01T00:00:00+00:00"}}
    svc._record_current_errors("vacuum.krumel_knecht", "cleaning", "2026-01-01T00:00:00+00:00", extras)

    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM robot_error_history WHERE entity_id=?", ("vacuum.krumel_knecht",)
        ).fetchone()
    assert row is not None
    assert row["source_entity_id"] == "sensor.krumel_knecht_error"
    assert row["raw_state"] == "battery_low"


def test_record_current_errors_still_uses_fehler_key_for_mower(temp_db):
    """Bestehendes Verhalten für Mähroboter (deutsches Sensor-Suffix) darf
    sich nicht ändern."""
    svc = RobotService()
    extras = {"fehler": {"state": "trapped", "last_changed": "2026-01-01T00:00:00+00:00"}}
    svc._record_current_errors("lawn_mower.robert", "mowing", "2026-01-01T00:00:00+00:00", extras)

    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM robot_error_history WHERE entity_id=?", ("lawn_mower.robert",)
        ).fetchone()
    assert row is not None
    assert row["source_entity_id"] == "sensor.robert_fehler"
    assert row["raw_state"] == "trapped"


def test_translate_error_state_knows_dust_bag_full():
    svc = RobotService.__new__(RobotService)
    assert svc._translate_error_state("dust_bag_full") == "Staubbeutel voll"
