from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers import ha_energy_costs as mod
from app.services.integration_config_service import IntegrationConfigService


def test_fixed_costs_zero_for_non_positive_annual():
    start = end = datetime(2026, 6, 14)
    assert mod._fixed_costs(start, end, 0.0) == 0.0
    assert mod._fixed_costs(start, end, -10.0) == 0.0


def test_fixed_costs_single_day_non_leap_year():
    start = end = datetime(2026, 6, 14)
    assert mod._fixed_costs(start, end, 365.0) == 1.0


def test_fixed_costs_multiple_days():
    start = datetime(2026, 6, 14)
    end = datetime(2026, 6, 16)
    assert mod._fixed_costs(start, end, 365.0) == 3.0


def test_energy_costs_without_fixed_costs():
    result = mod._energy_costs(ein_kwh=10, bez_kwh=5, feed_in_ct=8, grid_price_ct=30)
    assert result["einspeisung_value"] == 0.8
    assert result["netzbezug_cost"] == 1.5
    assert result["saldo"] == -0.7
    assert "fixed_costs" not in result


def test_energy_costs_with_fixed_costs():
    result = mod._energy_costs(ein_kwh=10, bez_kwh=5, feed_in_ct=8, grid_price_ct=30, fixed_costs=2.0)
    assert result["saldo"] == -2.7
    assert result["fixed_costs"] == 2.0


class FakeHA:
    def __init__(self, states):
        self._states = states

    def get_history(self, entity_id, start, end, chunk_hours=24):
        return self._states


def _state(value, iso_time):
    return {"state": str(value), "last_changed": iso_time}


def test_integrate_power_daily_from_history_signed_grid_sensor():
    ha = FakeHA([
        _state(1000, "2026-06-14T10:00:00+00:00"),
        _state(1000, "2026-06-14T10:30:00+00:00"),
        _state(0, "2026-06-14T11:00:00+00:00"),
    ])
    result = mod._integrate_power_daily_from_history("sensor.grid", None, None, ha, signed=True)
    assert result["2026-06-14"] == {"einspeisung": 1.0, "netzbezug": 0.0}


def test_integrate_power_daily_from_history_unsigned_device_sensor():
    ha = FakeHA([
        _state(1000, "2026-06-14T10:00:00+00:00"),
        _state(1000, "2026-06-14T10:30:00+00:00"),
        _state(0, "2026-06-14T11:00:00+00:00"),
    ])
    result = mod._integrate_power_daily_from_history("sensor.washer", None, None, ha, signed=False)
    assert result["2026-06-14"] == {"einspeisung": 0.0, "netzbezug": 1.0}


def test_integrate_power_daily_from_history_unsigned_ignores_negative_readings():
    ha = FakeHA([
        _state(-500, "2026-06-14T10:00:00+00:00"),
        _state(1000, "2026-06-14T10:30:00+00:00"),
    ])
    result = mod._integrate_power_daily_from_history("sensor.washer", None, None, ha, signed=False)
    assert result.get("2026-06-14", {"einspeisung": 0.0, "netzbezug": 0.0}) == {"einspeisung": 0.0, "netzbezug": 0.0}


def test_daily_series():
    daily = {
        "2026-06-10": {"einspeisung": 1.0, "netzbezug": 2.0},
        "2026-06-11": {"einspeisung": 1.5, "netzbezug": 2.5},
    }
    labels, ein, bez = mod._daily_series(daily, lambda dt: str(dt.day))
    assert labels == ["10", "11"]
    assert ein == [1.0, 1.5]
    assert bez == [2.0, 2.5]


def test_monthly_series():
    daily = {
        "2026-01-15": {"einspeisung": 1.0, "netzbezug": 2.0},
        "2026-01-20": {"einspeisung": 0.5, "netzbezug": 0.5},
        "2026-02-10": {"einspeisung": 3.0, "netzbezug": 4.0},
    }
    labels, ein, bez = mod._monthly_series(daily)
    assert labels == ["Jan", "Feb"]
    assert ein == [1.5, 3.0]
    assert bez == [2.5, 4.0]


def _configure_energy(sensors, tariffs=None):
    IntegrationConfigService().update_config({
        "energy": {
            "enabled": True,
            "sensors": sensors,
            "tariffs": tariffs or {},
        }
    })


class FakeHAProvider:
    """Drop-in replacement for HomeAssistantProvider used by the endpoint."""

    def __init__(self, *args, **kwargs):
        pass

    def get_history(self, entity_id, start, end, chunk_hours=24):
        return []


def test_history_endpoint_404_without_sensors(temp_db, monkeypatch):
    monkeypatch.setattr(mod, "HomeAssistantProvider", FakeHAProvider)
    app = FastAPI()
    app.include_router(mod.router)
    with TestClient(app) as client:
        resp = client.get("/ha/energy/history?view=today")
        assert resp.status_code == 404


def test_history_endpoint_today_returns_grid_and_device_sensors(temp_db, monkeypatch):
    _configure_energy(
        sensors=[
            {"entity_id": "sensor.grid", "label": "Gesamt", "role": "grid"},
            {"entity_id": "sensor.washer", "label": "Waschmaschine", "role": "device"},
        ],
        tariffs={"feed_in_ct": 8.0, "grid_price_ct": 30.0, "base_price_eur_year": 0, "extra_fees_eur_year": 0},
    )
    monkeypatch.setattr(mod, "HomeAssistantProvider", FakeHAProvider)

    app = FastAPI()
    app.include_router(mod.router)
    with TestClient(app) as client:
        resp = client.get("/ha/energy/history?view=today")
        assert resp.status_code == 200
        data = resp.json()
        assert data["view"] == "today"

        sensors_by_id = {s["id"]: s for s in data["sensors"]}
        assert sensors_by_id.keys() == {"gesamt", "waschmaschine"}

        grid = sensors_by_id["gesamt"]
        assert grid["role"] == "grid"
        assert grid["einspeisung"] == 0.0
        assert grid["netzbezug"] == 0.0
        assert "costs" in grid  # tariffs configured -> costs_enabled

        device = sensors_by_id["waschmaschine"]
        assert device["role"] == "device"
        assert device["verbrauch"] == 0.0
        assert device["cost"] == 0.0  # grid_price_ct > 0 -> cost is reported
