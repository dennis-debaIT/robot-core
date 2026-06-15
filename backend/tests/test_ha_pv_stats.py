import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers import ha_pv_stats as mod
from app.services.integration_config_service import IntegrationConfigService


def _state(value, iso_time):
    return {"state": str(value), "last_changed": iso_time}


def _stat_row(mean=None, state=None, start_iso=""):
    row: dict = {"start": start_iso}
    if mean is not None:
        row["mean"] = mean
    if state is not None:
        row["state"] = state
    return row


def test_history_to_5min_max():
    states = [
        _state(100, "2026-06-14T10:02:00+00:00"),
        _state(150, "2026-06-14T10:04:00+00:00"),
        _state(0, "2026-06-14T10:06:00+00:00"),  # <= 0 wird ignoriert
        _state(200, "2026-06-14T10:07:00+00:00"),
    ]
    labels, values = mod._history_to_5min_max(states)
    assert labels == ["12:00", "12:05"]
    assert values == [150.0, 200.0]


def test_history_to_daily_max():
    states = [
        _state(5, "2026-06-14T10:00:00+00:00"),
        _state(8, "2026-06-14T20:00:00+00:00"),
        _state(3, "2026-06-15T05:00:00+00:00"),
    ]
    daily = mod._history_to_daily_max(states)
    assert daily == {"2026-06-14": 8.0, "2026-06-15": 3.0}


class FakeHA:
    def __init__(self, history=None, stats=None, states=None):
        self._history = history or []
        self._stats = stats or {}
        self._states = states or {}

    def get_history(self, entity_id, start, end, chunk_hours=24):
        return self._history

    def get_state(self, entity_id):
        return self._states.get(entity_id)

    async def get_pv_statistics(self, entity_ids, start, end, period, types):
        return {eid: self._stats.get(eid, []) for eid in entity_ids}


def test_integrate_power_to_daily_kwh_from_history_basic():
    ha = FakeHA(history=[
        _state(1000, "2026-06-14T10:00:00+00:00"),
        _state(1000, "2026-06-14T10:30:00+00:00"),
        _state(0, "2026-06-14T11:00:00+00:00"),
    ])
    result = mod._integrate_power_to_daily_kwh_from_history("sensor.pv", None, None, ha)
    assert result["2026-06-14"] == 1.0


def test_integrate_power_to_daily_kwh_from_history_ignores_large_gaps():
    ha = FakeHA(history=[
        _state(1000, "2026-06-14T10:00:00+00:00"),
        _state(1000, "2026-06-14T11:00:00+00:00"),  # 60 min Lücke -> ignoriert
    ])
    result = mod._integrate_power_to_daily_kwh_from_history("sensor.pv", None, None, ha)
    assert result["2026-06-14"] == 0.0


def test_integrate_power_to_daily_kwh_from_history_ignores_negative_readings():
    ha = FakeHA(history=[
        _state(-100, "2026-06-14T10:00:00+00:00"),
        _state(1000, "2026-06-14T10:30:00+00:00"),
    ])
    result = mod._integrate_power_to_daily_kwh_from_history("sensor.pv", None, None, ha)
    assert result.get("2026-06-14") == 0.0


def test_integrate_power_to_daily_kwh_from_stats():
    ha = FakeHA(stats={"sensor.pv": [
        _stat_row(mean=1000, start_iso="2026-06-14T10:00:00+00:00"),
        _stat_row(mean=2000, start_iso="2026-06-14T11:00:00+00:00"),
    ]})
    result = asyncio.run(mod._integrate_power_to_daily_kwh_from_stats("sensor.pv", None, None, ha))
    assert result["2026-06-14"] == 3.0


def test_integrate_power_to_daily_kwh_from_stats_ignores_negative_mean():
    ha = FakeHA(stats={"sensor.pv": [
        _stat_row(mean=-500, start_iso="2026-06-14T10:00:00+00:00"),
        _stat_row(mean=1000, start_iso="2026-06-14T11:00:00+00:00"),
    ]})
    result = asyncio.run(mod._integrate_power_to_daily_kwh_from_stats("sensor.pv", None, None, ha))
    assert result["2026-06-14"] == 1.0


def test_integrate_power_to_daily_kwh_from_stats_empty_when_no_rows():
    ha = FakeHA(stats={})
    result = asyncio.run(mod._integrate_power_to_daily_kwh_from_stats("sensor.pv", None, None, ha))
    assert result == {}


def test_integrate_power_to_daily_kwh_short_range_uses_history():
    ha = FakeHA(
        history=[
            _state(1000, "2026-06-14T10:00:00+00:00"),
            _state(1000, "2026-06-14T10:30:00+00:00"),
        ],
        stats={"sensor.pv": [_stat_row(mean=5000, start_iso="2026-06-14T10:00:00+00:00")]},
    )
    start = datetime(2026, 6, 14, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 14, 23, 0, tzinfo=timezone.utc)  # <= 36h
    result = asyncio.run(mod._integrate_power_to_daily_kwh("sensor.pv", start, end, ha))
    assert result["2026-06-14"] == 0.5


def test_integrate_power_to_daily_kwh_long_range_uses_stats_for_past_period():
    ha = FakeHA(stats={"sensor.pv": [
        _stat_row(mean=1000, start_iso="2026-01-15T10:00:00+00:00"),
        _stat_row(mean=2000, start_iso="2026-01-15T11:00:00+00:00"),
    ]})
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 31, tzinfo=timezone.utc)  # liegt vollständig in der Vergangenheit
    result = asyncio.run(mod._integrate_power_to_daily_kwh("sensor.pv", start, end, ha))
    assert result["2026-01-15"] == 3.0


def test_integrate_power_to_daily_kwh_falls_back_to_history_if_stats_empty():
    ha = FakeHA(
        history=[
            _state(1000, "2026-01-15T10:00:00+00:00"),
            _state(1000, "2026-01-15T10:30:00+00:00"),
        ],
        stats={},
    )
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 31, tzinfo=timezone.utc)
    result = asyncio.run(mod._integrate_power_to_daily_kwh("sensor.pv", start, end, ha))
    assert result["2026-01-15"] == 0.5


def test_integrate_power_to_daily_kwh_merges_today_from_history():
    now_loc = datetime.now(mod._LOCAL_TZ)
    now_utc = now_loc.astimezone(timezone.utc)
    today_key = now_loc.strftime("%Y-%m-%d")

    today_reading_loc = now_loc.replace(hour=10, minute=0, second=0, microsecond=0)
    today_reading_utc = today_reading_loc.astimezone(timezone.utc)
    history = [
        _state(1000, today_reading_utc.isoformat()),
        _state(1000, (today_reading_utc + timedelta(minutes=30)).isoformat()),
    ]
    ha = FakeHA(
        history=history,
        stats={"sensor.pv": [_stat_row(mean=5000, start_iso="2026-01-15T10:00:00+00:00")]},
    )

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = asyncio.run(mod._integrate_power_to_daily_kwh("sensor.pv", start, now_utc, ha))

    assert result["2026-01-15"] == 5.0  # aus Langzeitstatistik
    assert result[today_key] == 0.5     # heutiger Tag per History überschrieben


def _configure_pv(power="", daily=""):
    IntegrationConfigService().update_config({
        "pv": {"sensors": {"power": power, "daily": daily}}
    })


def test_history_endpoint_today_400_without_power_sensor(temp_db, monkeypatch):
    _configure_pv(power="", daily="")
    ha = FakeHA()
    monkeypatch.setattr(mod, "HomeAssistantProvider", lambda: ha)
    app = FastAPI()
    app.include_router(mod.router)
    with TestClient(app) as client:
        resp = client.get("/ha/pv/history?view=today")
        assert resp.status_code == 400


def test_history_endpoint_7days_400_without_any_sensor(temp_db, monkeypatch):
    _configure_pv(power="", daily="")
    ha = FakeHA()
    monkeypatch.setattr(mod, "HomeAssistantProvider", lambda: ha)
    app = FastAPI()
    app.include_router(mod.router)
    with TestClient(app) as client:
        resp = client.get("/ha/pv/history?view=7days")
        assert resp.status_code == 400


def test_history_endpoint_unknown_view(temp_db, monkeypatch):
    _configure_pv(power="sensor.pv_power", daily="")
    ha = FakeHA()
    monkeypatch.setattr(mod, "HomeAssistantProvider", lambda: ha)
    app = FastAPI()
    app.include_router(mod.router)
    with TestClient(app) as client:
        resp = client.get("/ha/pv/history?view=nonsense")
        assert resp.status_code == 400


def test_history_endpoint_today_total_derived_from_power_sensor(temp_db, monkeypatch):
    _configure_pv(power="sensor.pv_power", daily="")
    now_loc = datetime.now(mod._LOCAL_TZ)
    reading_loc = now_loc.replace(hour=10, minute=0, second=0, microsecond=0)
    reading_utc = reading_loc.astimezone(timezone.utc)
    ha = FakeHA(
        history=[
            _state(1000, reading_utc.isoformat()),
            _state(1000, (reading_utc + timedelta(minutes=30)).isoformat()),
        ],
        states={"sensor.pv_power": {"state": "0"}},
    )
    monkeypatch.setattr(mod, "HomeAssistantProvider", lambda: ha)
    app = FastAPI()
    app.include_router(mod.router)
    with TestClient(app) as client:
        resp = client.get("/ha/pv/history?view=today")
        assert resp.status_code == 200
        data = resp.json()
        assert data["view"] == "today"
        assert data["unit"] == "W"
        assert data["total_unit"] == "kWh"
        assert data["total"] == 0.5


def test_history_endpoint_today_total_from_daily_sensor(temp_db, monkeypatch):
    _configure_pv(power="sensor.pv_power", daily="sensor.pv_daily")
    ha = FakeHA(
        history=[],
        states={"sensor.pv_power": {"state": "0"}, "sensor.pv_daily": {"state": "12.34"}},
    )
    monkeypatch.setattr(mod, "HomeAssistantProvider", lambda: ha)
    app = FastAPI()
    app.include_router(mod.router)
    with TestClient(app) as client:
        resp = client.get("/ha/pv/history?view=today")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 12.34


def test_history_endpoint_7days_with_daily_sensor_stats(temp_db, monkeypatch):
    _configure_pv(power="", daily="sensor.pv_daily")
    now_loc = datetime.now(mod._LOCAL_TZ)
    day_start_utc = now_loc.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    ha = FakeHA(stats={"sensor.pv_daily": [
        _stat_row(state=5.5, start_iso=day_start_utc.isoformat()),
    ]})
    monkeypatch.setattr(mod, "HomeAssistantProvider", lambda: ha)
    app = FastAPI()
    app.include_router(mod.router)
    with TestClient(app) as client:
        resp = client.get("/ha/pv/history?view=7days")
        assert resp.status_code == 200
        data = resp.json()
        assert data["view"] == "7days"
        assert data["unit"] == "kWh"
        assert data["total"] == 5.5
        assert len(data["labels"]) == 1


def test_history_endpoint_year_power_sensor_uses_monthly_stats(temp_db, monkeypatch):
    _configure_pv(power="sensor.pv_power", daily="")
    now_loc = datetime.now(mod._LOCAL_TZ)
    jan_start_utc = now_loc.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    ha = FakeHA(stats={"sensor.pv_power": [
        _stat_row(mean=100.0, start_iso=jan_start_utc.isoformat()),
    ]})
    monkeypatch.setattr(mod, "HomeAssistantProvider", lambda: ha)
    app = FastAPI()
    app.include_router(mod.router)
    with TestClient(app) as client:
        resp = client.get("/ha/pv/history?view=year")
        assert resp.status_code == 200
        data = resp.json()
        assert data["view"] == "year"
        assert data["labels"] == ["Jan"]
        assert data["values"] == [round(100.0 * 31 * 24 / 1000, 1)]
