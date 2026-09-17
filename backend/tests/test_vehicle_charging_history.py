from datetime import datetime, timedelta, timezone

import app.search.providers.homeassistant as ha_module
from app.database.db import get_connection
from app.services.vehicle_service import VehicleService, _DE_MONTHS_SHORT


def _insert_raw(vehicle_id, recorded_at_iso, battery_pct):
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO vehicle_charging_history(
                vehicle_id, battery_pct, is_charging, plug_connected, recorded_at, imported_at
            ) VALUES (?, ?, 0, 0, ?, ?)
            """,
            (vehicle_id, battery_pct, recorded_at_iso, recorded_at_iso),
        )


class FakeHA:
    def __init__(self, history):
        self._history = history

    def get_history(self, entity_id, start, end, chunk_hours=24):
        return self._history


def test_update_charging_daily_backfill(temp_db):
    svc = VehicleService()
    tz = svc._local_tz()
    now_utc = datetime.now(timezone.utc)
    now_loc = now_utc.astimezone(tz)
    day1 = (now_loc - timedelta(days=2)).strftime("%Y-%m-%d")
    day2 = (now_loc - timedelta(days=1)).strftime("%Y-%m-%d")

    for pct, day, hour in [(80, day1, 8), (100, day1, 18), (50, day2, 8), (90, day2, 18)]:
        recorded = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=tz, hour=hour).astimezone(timezone.utc)
        _insert_raw("veh1", recorded.isoformat(), pct)

    with get_connection() as conn:
        svc._update_charging_daily(conn, "veh1", now_utc)

    with get_connection() as conn:
        rows = {
            r["day"]: r
            for r in conn.execute("SELECT * FROM vehicle_charging_daily WHERE vehicle_id='veh1'").fetchall()
        }

    assert rows[day1]["min_pct"] == 80.0
    assert rows[day1]["max_pct"] == 100.0
    assert rows[day1]["charged_pct"] == 20.0
    assert rows[day2]["min_pct"] == 50.0
    assert rows[day2]["max_pct"] == 90.0
    assert rows[day2]["charged_pct"] == 40.0


def test_update_charging_daily_incremental_only_updates_today(temp_db):
    svc = VehicleService()
    tz = svc._local_tz()
    now_utc = datetime.now(timezone.utc)
    now_loc = now_utc.astimezone(tz)
    yesterday = (now_loc - timedelta(days=1)).strftime("%Y-%m-%d")
    today = now_loc.strftime("%Y-%m-%d")

    yesterday_recorded = datetime.strptime(yesterday, "%Y-%m-%d").replace(tzinfo=tz, hour=12).astimezone(timezone.utc)
    _insert_raw("veh1", yesterday_recorded.isoformat(), 60)

    with get_connection() as conn:
        svc._update_charging_daily(conn, "veh1", now_utc)

    with get_connection() as conn:
        before = dict(conn.execute(
            "SELECT min_pct, max_pct FROM vehicle_charging_daily WHERE vehicle_id='veh1' AND day=?",
            (yesterday,),
        ).fetchone())

    _insert_raw("veh1", now_utc.isoformat(), 77)
    with get_connection() as conn:
        svc._update_charging_daily(conn, "veh1", now_utc)

    with get_connection() as conn:
        after = dict(conn.execute(
            "SELECT min_pct, max_pct FROM vehicle_charging_daily WHERE vehicle_id='veh1' AND day=?",
            (yesterday,),
        ).fetchone())
        today_row = conn.execute(
            "SELECT min_pct, max_pct FROM vehicle_charging_daily WHERE vehicle_id='veh1' AND day=?",
            (today,),
        ).fetchone()

    assert after == before
    assert today_row["min_pct"] == 77.0
    assert today_row["max_pct"] == 77.0


def test_charging_history_7days_reads_daily_aggregate(temp_db):
    svc = VehicleService()
    tz = svc._local_tz()
    now = datetime.now(tz)
    target_day = (now - timedelta(days=2)).strftime("%Y-%m-%d")

    with get_connection() as conn:
        conn.execute(
            "INSERT INTO vehicle_charging_daily(vehicle_id, day, min_pct, max_pct, charged_pct, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("veh1", target_day, 25.0, 80.0, 55.0, now.isoformat()),
        )

    result = svc.charging_history("veh1", "7days")

    day_keys = [(now - timedelta(days=6 - i)).strftime("%Y-%m-%d") for i in range(7)]
    idx = day_keys.index(target_day)
    assert result["min_pct"][idx] == 25.0
    assert result["max_pct"][idx] == 80.0
    assert result["charged_pct"][idx] == 55.0


def test_charging_history_month_ha_fallback_for_missing_day(temp_db, monkeypatch):
    svc = VehicleService()
    tz = svc._local_tz()
    now = datetime.now(tz)
    today_8  = now.replace(hour=8, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    today_20 = now.replace(hour=20, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    states = [
        {"state": "40", "last_changed": today_8.isoformat()},
        {"state": "95", "last_changed": today_20.isoformat()},
    ]
    monkeypatch.setattr(ha_module, "HomeAssistantProvider", lambda: FakeHA(states))

    result = svc.charging_history("veh2", "month", battery_entity="sensor.battery")

    assert result["min_pct"][-1] == 40.0
    assert result["max_pct"][-1] == 95.0


def test_charging_history_year_aggregates_by_month(temp_db):
    svc = VehicleService()
    tz = svc._local_tz()
    now = datetime.now(tz)
    year = now.year

    with get_connection() as conn:
        conn.executemany(
            "INSERT INTO vehicle_charging_daily(vehicle_id, day, min_pct, max_pct, charged_pct, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("veh3", f"{year}-01-05", 30.0, 90.0, 60.0, now.isoformat()),
                ("veh3", f"{year}-01-10", 20.0, 100.0, 80.0, now.isoformat()),
                ("veh3", f"{year}-02-03", 50.0, 70.0, 20.0, now.isoformat()),
            ],
        )

    result = svc.charging_history("veh3", "year")

    assert result["period"] == "year"
    assert result["labels"][:2] == [_DE_MONTHS_SHORT[0], _DE_MONTHS_SHORT[1]]
    assert result["min_pct"][0] == 20.0
    assert result["max_pct"][0] == 100.0
    assert result["charged_pct"][0] == 140.0
    assert result["min_pct"][1] == 50.0
    assert result["max_pct"][1] == 70.0
    assert result["charged_pct"][1] == 20.0


def test_charging_history_year_empty_when_no_data(temp_db):
    svc = VehicleService()
    result = svc.charging_history("veh_unknown", "year")
    assert result["labels"] == []
    assert result["min_pct"] == []
    assert result["max_pct"] == []
    assert result["charged_pct"] == []


# ── Extrahierte Lade-/Steckerkennung (Regressionsschutz für die Insight-Wiederverwendung) ──

def test_is_charging_state_matches_known_values():
    assert VehicleService._is_charging_state("charging") is True
    assert VehicleService._is_charging_state("ON") is True
    assert VehicleService._is_charging_state("in_charge") is True
    assert VehicleService._is_charging_state("not_charging") is False
    assert VehicleService._is_charging_state("") is False
    assert VehicleService._is_charging_state(None) is False


def test_is_plug_connected_state_matches_known_values():
    assert VehicleService._is_plug_connected_state("plugged_in") is True
    assert VehicleService._is_plug_connected_state("connected") is True
    assert VehicleService._is_plug_connected_state("charging") is True
    assert VehicleService._is_plug_connected_state("off") is False
    assert VehicleService._is_plug_connected_state(None) is False


class FakeHAStates:
    def __init__(self, states):
        self._states = states

    def get_state(self, entity_id):
        return self._states.get(entity_id)


def test_record_charging_uses_extracted_state_helpers(temp_db):
    """Regressionsschutz: nach dem Herausziehen der Lade-/Steckererkennung
    in eigene Staticmethods (für die Wiederverwendung im proaktiven
    Fahrzeug-Insight) muss record_charging() weiterhin identisch werten."""
    vehicle_cfg = VehicleService.default_vehicle()
    vehicle_cfg["id"] = "veh_test"
    vehicle_cfg["ev_profile_enabled"] = True
    vehicle_cfg["battery_entity"] = "sensor.battery"
    vehicle_cfg["charging_entity"] = "sensor.charging"
    vehicle_cfg["plug_entity"] = "binary_sensor.plug"

    states = {
        "sensor.battery": {"state": "77", "attributes": {}},
        "sensor.charging": {"state": "charging", "attributes": {}},
        "binary_sensor.plug": {"state": "connected", "attributes": {}},
    }
    svc = VehicleService(ha=FakeHAStates(states))
    config = {"vehicles": {"items": [vehicle_cfg]}}
    svc.record_charging(config)

    with get_connection() as conn:
        row = conn.execute(
            "SELECT is_charging, plug_connected FROM vehicle_charging_history WHERE vehicle_id=?",
            ("veh_test",),
        ).fetchone()
    assert row["is_charging"] == 1
    assert row["plug_connected"] == 1
