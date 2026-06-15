from app.database.db import get_connection, read_state, write_state
from app.services.integration_config_service import IntegrationConfigService


def test_sanitize_tariff_ct_rounds_and_clamps():
    assert IntegrationConfigService._sanitize_tariff_ct(12.345) == 12.35
    assert IntegrationConfigService._sanitize_tariff_ct(500) == 200.0
    assert IntegrationConfigService._sanitize_tariff_ct(-5) == 0.0
    assert IntegrationConfigService._sanitize_tariff_ct("abc") == 0.0
    assert IntegrationConfigService._sanitize_tariff_ct(None) == 0.0
    assert IntegrationConfigService._sanitize_tariff_ct(float("nan")) == 0.0


def test_sanitize_tariff_eur_year_clamps():
    assert IntegrationConfigService._sanitize_tariff_eur_year(50.4) == 50.4
    assert IntegrationConfigService._sanitize_tariff_eur_year(50000) == 10000.0
    assert IntegrationConfigService._sanitize_tariff_eur_year(-1) == 0.0


def test_sanitize_energy_sensors_non_list_returns_empty():
    assert IntegrationConfigService._sanitize_energy_sensors(None) == []
    assert IntegrationConfigService._sanitize_energy_sensors("nope") == []


def test_sanitize_energy_sensors_filters_entries_without_entity_id():
    result = IntegrationConfigService._sanitize_energy_sensors([
        {"entity_id": "", "label": "Leer"},
        {"label": "Ohne entity_id"},
        "not-a-dict",
    ])
    assert result == []


def test_sanitize_energy_sensors_label_defaults_to_entity_id():
    result = IntegrationConfigService._sanitize_energy_sensors([
        {"entity_id": "sensor.foo"},
    ])
    assert result[0]["label"] == "sensor.foo"
    assert result[0]["role"] == "device"


def test_sanitize_energy_sensors_label_truncated_to_40_chars():
    result = IntegrationConfigService._sanitize_energy_sensors([
        {"entity_id": "sensor.foo", "label": "x" * 60},
    ])
    assert result[0]["label"] == "x" * 40


def test_sanitize_energy_sensors_only_first_grid_role_kept():
    result = IntegrationConfigService._sanitize_energy_sensors([
        {"entity_id": "sensor.a", "label": "A", "role": "grid"},
        {"entity_id": "sensor.b", "label": "B", "role": "grid"},
    ])
    assert result[0]["role"] == "grid"
    assert result[1]["role"] == "device"


def test_sanitize_energy_sensors_unknown_role_defaults_to_device():
    result = IntegrationConfigService._sanitize_energy_sensors([
        {"entity_id": "sensor.a", "label": "A", "role": "whatever"},
    ])
    assert result[0]["role"] == "device"


def test_sanitize_energy_sensors_duplicate_labels_get_unique_ids():
    result = IntegrationConfigService._sanitize_energy_sensors([
        {"entity_id": "sensor.a", "label": "Geraet"},
        {"entity_id": "sensor.b", "label": "Geraet"},
    ])
    assert [s["id"] for s in result] == ["geraet", "geraet-2"]


def test_sanitize_energy_sensors_limits_to_12():
    items = [{"entity_id": f"sensor.{i}", "label": f"Sensor {i}"} for i in range(20)]
    result = IntegrationConfigService._sanitize_energy_sensors(items)
    assert len(result) == 12


def test_pv_grid_migration_runs_once_and_persists(temp_db):
    old_state = IntegrationConfigService().default_config()
    del old_state["energy"]
    old_state["pv"]["sensors"]["grid"] = "sensor.netzbezug"
    old_state["pv"]["tariffs"] = {
        "feed_in_ct": 8.2,
        "grid_price_ct": 32.5,
        "base_price_eur_year": 50.4,
        "extra_fees_eur_year": 0.0,
    }
    with get_connection() as conn:
        write_state(conn, IntegrationConfigService.state_key, old_state)

    config = IntegrationConfigService().get_config()

    assert config["energy"]["enabled"] is True
    assert config["energy"]["tariffs"]["base_price_eur_year"] == 50.4
    assert config["energy"]["sensors"] == [
        {"id": "gesamt-netzbezug", "label": "Gesamt-Netzbezug", "entity_id": "sensor.netzbezug", "role": "grid"},
    ]

    with get_connection() as conn:
        stored = read_state(conn, IntegrationConfigService.state_key, {})
    assert "energy" in stored
    assert stored["energy"]["sensors"][0]["entity_id"] == "sensor.netzbezug"


def test_pv_grid_migration_does_not_rerun_after_pv_tariffs_change(temp_db):
    old_state = IntegrationConfigService().default_config()
    del old_state["energy"]
    old_state["pv"]["sensors"]["grid"] = "sensor.netzbezug"
    old_state["pv"]["tariffs"]["base_price_eur_year"] = 50.4
    with get_connection() as conn:
        write_state(conn, IntegrationConfigService.state_key, old_state)

    svc = IntegrationConfigService()
    svc.get_config()  # triggers + persists the one-time migration

    with get_connection() as conn:
        stored = read_state(conn, IntegrationConfigService.state_key, {})
    stored["pv"]["tariffs"]["base_price_eur_year"] = 99.0
    with get_connection() as conn:
        write_state(conn, IntegrationConfigService.state_key, stored)

    config = svc.get_config()
    assert config["energy"]["tariffs"]["base_price_eur_year"] == 50.4


def test_no_migration_without_pv_grid_sensor(temp_db):
    config = IntegrationConfigService().get_config()
    assert config["energy"]["enabled"] is False
    assert config["energy"]["sensors"] == []
