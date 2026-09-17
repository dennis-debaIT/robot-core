from datetime import datetime, timedelta, timezone

import app.services.insight_service as insight_module
from app.database.db import get_connection, read_state
from app.services.insight_service import InsightService
from app.services.integration_config_service import IntegrationConfigService


class _FixedDateTime(datetime):
    """Ersetzt datetime.now() im insight_service-Modul für Zeit-Gating-Tests."""
    _fixed = datetime(2026, 1, 1, 19, 0, 0)

    @classmethod
    def now(cls, tz=None):
        if tz is not None:
            return cls._fixed.replace(tzinfo=tz)
        return cls._fixed


def _set_fixed_hour(monkeypatch, hour: int) -> None:
    fixed = _FixedDateTime
    fixed._fixed = datetime(2026, 1, 1, hour, 0, 0)
    monkeypatch.setattr(insight_module, "datetime", fixed)


class FakeNotifications:
    def __init__(self):
        self.created = []

    def create_manual_notification(self, message, entity_id=None):
        self.created.append({"message": message, "entity_id": entity_id})
        return len(self.created)


class FakePv:
    def __init__(self, grid_value):
        self._grid_value = grid_value

    def get_state(self, sensors):
        if self._grid_value is None:
            return {}
        return {"grid": {"value": str(self._grid_value)}}


class FakeWeather:
    def __init__(self, home_tomorrow, dest_tomorrow=None):
        self._home_tomorrow = home_tomorrow
        self._dest_tomorrow = dest_tomorrow

    def get_display_data(self, location=None):
        if location:
            return {"tomorrow": self._dest_tomorrow} if self._dest_tomorrow else None
        return {"tomorrow": self._home_tomorrow}


class FakeHAProviderFuel:
    """Für Kraftstoff-Tests: liefert einen konfigurierbaren aktuellen Preis
    plus eine synthetische 7-Tage-Historie."""
    def __init__(self, current_price: float, history_prices: list[float]):
        self._current_price = current_price
        self._history_prices = history_prices

    def get_fuel_prices(self):
        return {"grouped": {"Diesel": [
            {"entity_id": "sensor.diesel_test", "name": "Diesel Test", "fuel_type": "Diesel",
             "price": self._current_price, "unit": "€/L", "last_changed": ""},
        ]}}

    def get_history(self, entity_id, start, end, chunk_hours=2):
        return [{"state": str(p)} for p in self._history_prices]


class FakeHAProviderEvents:
    def __init__(self, events):
        self._events = events

    def get_events_upcoming(self, days=7, selected_calendars=None, exclude_calendars=None):
        return self._events


def _enable_insight(config_patch: dict) -> None:
    IntegrationConfigService().update_config(config_patch)


def _fake_llm(monkeypatch, reply: str = "LLM-Text", capture: dict | None = None):
    class FakeRouter:
        def generate(self, payload, timeout_seconds=15):
            if capture is not None:
                capture.update(payload)
            return {"reply": reply}
    monkeypatch.setattr("app.brain.llm_client.LLMRouter", FakeRouter)


# ── Kraftstoffpreis-Trend ────────────────────────────────────────

def test_fuel_price_no_run_before_18_uhr(monkeypatch, temp_db):
    _set_fixed_hour(monkeypatch, 17)
    svc = InsightService(notifications=FakeNotifications())
    result = svc._check_fuel_price({"fuel_prices": {"fuel_types": ["diesel"]}})
    assert result is None


def test_fuel_price_fires_near_weekly_low(monkeypatch, temp_db):
    _set_fixed_hour(monkeypatch, 19)
    monkeypatch.setattr(
        insight_module, "HomeAssistantProvider",
        lambda: FakeHAProviderFuel(current_price=1.550, history_prices=[1.650, 1.630, 1.600, 1.580, 1.550]),
    )
    _fake_llm(monkeypatch, reply="Diesel ist deutlich gefallen, wird wohl nicht mehr viel sinken.")
    svc = InsightService(notifications=FakeNotifications())
    result = svc._check_fuel_price({"fuel_prices": {"fuel_types": ["diesel"]}})
    assert result == "Diesel ist deutlich gefallen, wird wohl nicht mehr viel sinken."


def test_fuel_price_no_fire_on_stable_price(monkeypatch, temp_db):
    _set_fixed_hour(monkeypatch, 19)
    monkeypatch.setattr(
        insight_module, "HomeAssistantProvider",
        lambda: FakeHAProviderFuel(current_price=1.600, history_prices=[1.598, 1.602, 1.601, 1.599, 1.600]),
    )
    svc = InsightService(notifications=FakeNotifications())
    result = svc._check_fuel_price({"fuel_prices": {"fuel_types": ["diesel"]}})
    assert result is None


def test_fuel_price_second_run_same_day_skipped(monkeypatch, temp_db):
    _set_fixed_hour(monkeypatch, 19)
    monkeypatch.setattr(
        insight_module, "HomeAssistantProvider",
        lambda: FakeHAProviderFuel(current_price=1.550, history_prices=[1.650, 1.600, 1.550]),
    )
    _fake_llm(monkeypatch, reply="Diesel ist billiger geworden.")
    svc = InsightService(notifications=FakeNotifications())
    first = svc._check_fuel_price({"fuel_prices": {"fuel_types": ["diesel"]}})
    assert first is not None
    second = svc._check_fuel_price({"fuel_prices": {"fuel_types": ["diesel"]}})
    assert second is None


def test_fuel_price_llm_failure_falls_back_to_template(monkeypatch, temp_db):
    _set_fixed_hour(monkeypatch, 19)
    monkeypatch.setattr(
        insight_module, "HomeAssistantProvider",
        lambda: FakeHAProviderFuel(current_price=1.550, history_prices=[1.650, 1.600, 1.550]),
    )

    class FailingRouter:
        def generate(self, payload, timeout_seconds=15):
            raise RuntimeError("kein Netzwerk")
    monkeypatch.setattr("app.brain.llm_client.LLMRouter", FailingRouter)

    svc = InsightService(notifications=FakeNotifications())
    result = svc._check_fuel_price({"fuel_prices": {"fuel_types": ["diesel"]}})
    assert result  # nie leer
    assert "Diesel" in result


# ── PV-Überschuss ─────────────────────────────────────────────────

def test_pv_surplus_fires_above_threshold(monkeypatch, temp_db):
    _fake_llm(monkeypatch, reply="Gerade viel PV-Strom übrig, jetzt wäre ein guter Moment für die Waschmaschine.")
    svc = InsightService(pv=FakePv(2000), notifications=FakeNotifications())
    result = svc._check_pv_surplus({"pv": {"enabled": True, "sensors": {}}}, {"pv_surplus_threshold_watts": 1500})
    assert result == "Gerade viel PV-Strom übrig, jetzt wäre ein guter Moment für die Waschmaschine."
    with get_connection() as conn:
        assert bool(read_state(conn, "insight_pv_surplus_active", False)) is True


def test_pv_surplus_no_refire_while_active(monkeypatch, temp_db):
    _fake_llm(monkeypatch, reply="Viel PV-Überschuss gerade.")
    svc = InsightService(pv=FakePv(2000), notifications=FakeNotifications())
    cfg = {"pv": {"enabled": True, "sensors": {}}}
    insights_cfg = {"pv_surplus_threshold_watts": 1500}
    first = svc._check_pv_surplus(cfg, insights_cfg)
    assert first is not None
    second = svc._check_pv_surplus(cfg, insights_cfg)
    assert second is None


def test_pv_surplus_resets_when_below_threshold(monkeypatch, temp_db):
    _fake_llm(monkeypatch, reply="Viel PV-Überschuss.")
    cfg = {"pv": {"enabled": True, "sensors": {}}}
    insights_cfg = {"pv_surplus_threshold_watts": 1500}
    svc_high = InsightService(pv=FakePv(2000), notifications=FakeNotifications())
    assert svc_high._check_pv_surplus(cfg, insights_cfg) is not None
    svc_low = InsightService(pv=FakePv(500), notifications=FakeNotifications())
    assert svc_low._check_pv_surplus(cfg, insights_cfg) is None
    with get_connection() as conn:
        assert bool(read_state(conn, "insight_pv_surplus_active", False)) is False


def test_pv_surplus_skips_without_grid_sensor(monkeypatch, temp_db):
    svc = InsightService(pv=FakePv(None), notifications=FakeNotifications())
    result = svc._check_pv_surplus({"pv": {"enabled": True, "sensors": {}}}, {"pv_surplus_threshold_watts": 1500})
    assert result is None


def test_pv_surplus_disabled_module_skips(monkeypatch, temp_db):
    svc = InsightService(pv=FakePv(2000), notifications=FakeNotifications())
    result = svc._check_pv_surplus({"pv": {"enabled": False, "sensors": {}}}, {"pv_surplus_threshold_watts": 1500})
    assert result is None


# ── Wetter morgen (+ Kalender-Kombi) ───────────────────────────────

def test_weather_no_run_before_17_uhr(monkeypatch, temp_db):
    _set_fixed_hour(monkeypatch, 16)
    svc = InsightService(
        weather_cls=lambda: FakeWeather({"description": "Regen", "precipitation": 10, "temp_min": 10, "temp_max": 15}),
        notifications=FakeNotifications(),
    )
    result = svc._check_weather_tomorrow({"calendar": {}})
    assert result is None


def test_weather_fires_on_notable_home_weather(monkeypatch, temp_db):
    _set_fixed_hour(monkeypatch, 18)
    monkeypatch.setattr(insight_module, "HomeAssistantProvider", lambda: FakeHAProviderEvents([]))
    _fake_llm(monkeypatch, reply="Morgen regnet es, nimm die Jacke mit.")
    svc = InsightService(
        weather_cls=lambda: FakeWeather({"description": "Regen", "precipitation": 5, "temp_min": 10, "temp_max": 15}),
        notifications=FakeNotifications(),
    )
    result = svc._check_weather_tomorrow({"calendar": {}})
    assert result == "Morgen regnet es, nimm die Jacke mit."


def test_weather_no_fire_when_nothing_notable(monkeypatch, temp_db):
    _set_fixed_hour(monkeypatch, 18)
    monkeypatch.setattr(insight_module, "HomeAssistantProvider", lambda: FakeHAProviderEvents([]))
    svc = InsightService(
        weather_cls=lambda: FakeWeather({"description": "Sonnig", "precipitation": 0, "temp_min": 15, "temp_max": 22}),
        notifications=FakeNotifications(),
    )
    result = svc._check_weather_tomorrow({"calendar": {}})
    assert result is None


def test_weather_combines_calendar_event_location(monkeypatch, temp_db):
    _set_fixed_hour(monkeypatch, 18)
    tomorrow_iso = (_FixedDateTime._fixed + timedelta(days=1)).strftime("%Y-%m-%dT10:00:00+00:00")
    events = [{
        "summary": "Termin Darmstadt",
        "location": "Darmstadt",
        "start": {"dateTime": tomorrow_iso},
    }]
    monkeypatch.setattr(insight_module, "HomeAssistantProvider", lambda: FakeHAProviderEvents(events))
    captured = {}
    _fake_llm(monkeypatch, reply="Morgen nach Darmstadt, dort soll es regnen — zieh dich warm an.", capture=captured)
    svc = InsightService(
        weather_cls=lambda: FakeWeather(
            {"description": "Sonnig", "precipitation": 0, "temp_min": 15, "temp_max": 22},
            dest_tomorrow={"description": "Regen", "precipitation": 8, "temp_min": 8, "temp_max": 12},
        ),
        notifications=FakeNotifications(),
    )
    result = svc._check_weather_tomorrow({"calendar": {"selected_calendars": []}})
    assert result == "Morgen nach Darmstadt, dort soll es regnen — zieh dich warm an."
    user_prompt = captured["messages"][1]["content"]
    assert "Darmstadt" in user_prompt


# ── run_checks: Toggles ────────────────────────────────────────────

def test_run_checks_skips_disabled_sources(temp_db):
    # Insights sind standardmäßig aktiv (opt-out) — für diesen Test explizit
    # abschalten, um das Überspringen bei deaktivierter Quelle zu prüfen.
    _enable_insight({"insights": {
        "fuel_price_enabled": False,
        "pv_surplus_enabled": False,
        "weather_tomorrow_enabled": False,
    }})

    class ExplodingPv:
        def get_state(self, sensors):
            raise AssertionError("sollte bei deaktiviertem Insight nicht aufgerufen werden")

    svc = InsightService(pv=ExplodingPv(), notifications=FakeNotifications())
    fired = svc.run_checks()
    assert fired == []


def test_run_checks_creates_notification_for_fired_insight(monkeypatch, temp_db):
    _enable_insight({"insights": {"pv_surplus_enabled": True}, "pv": {"enabled": True, "sensors": {}}})
    _fake_llm(monkeypatch, reply="Viel PV-Überschuss gerade.")
    notifications = FakeNotifications()
    svc = InsightService(pv=FakePv(2000), notifications=notifications)
    fired = svc.run_checks()
    assert len(fired) == 1
    assert fired[0]["kind"] == "pv_surplus"
    assert len(notifications.created) == 1
    assert notifications.created[0]["entity_id"] == "pv"
