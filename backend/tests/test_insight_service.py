from datetime import datetime, timedelta, timezone

import app.services.insight_service as insight_module
from app.database.db import get_connection, read_state, write_state
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

    def create_manual_notification(self, message, entity_id=None, title="Erika"):
        self.created.append({"message": message, "entity_id": entity_id, "title": title})
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


def test_pv_surplus_avoids_repeating_previous_message(monkeypatch, temp_db):
    """Regression: der Nutzer bemerkte, dass PV-Meldungen sich wortgleich
    wiederholten — die zweite Formulierung muss die erste als
    Negativbeispiel im Prompt sehen und tatsächlich etwas anderes liefern."""
    cfg = {"pv": {"enabled": True, "sensors": {}}}
    insights_cfg = {"pv_surplus_threshold_watts": 1500}
    replies = iter(["Erste Formulierung.", "Zweite, andere Formulierung."])
    captured_prompts = []

    class TrackingRouter:
        def generate(self, payload, timeout_seconds=15):
            captured_prompts.append(payload["messages"][0]["content"])
            return {"reply": next(replies)}

    monkeypatch.setattr("app.brain.llm_client.LLMRouter", TrackingRouter)

    first = InsightService(pv=FakePv(2000), notifications=FakeNotifications())._check_pv_surplus(cfg, insights_cfg)
    assert first == "Erste Formulierung."

    InsightService(pv=FakePv(500), notifications=FakeNotifications())._check_pv_surplus(cfg, insights_cfg)  # Reset

    # Cooldown künstlich umgehen (Test läuft in Millisekunden ab, der reale
    # 2h-Cooldown würde das zweite Feuern sonst blockieren — hier geht's
    # nur um die Wiederholungs-Vermeidung, nicht um den Cooldown selbst).
    with get_connection() as conn:
        write_state(conn, "insight_pv_surplus_last_fired_at", "2020-01-01T00:00:00+00:00")

    second = InsightService(pv=FakePv(2000), notifications=FakeNotifications())._check_pv_surplus(cfg, insights_cfg)
    assert second == "Zweite, andere Formulierung."
    assert len(captured_prompts) == 2
    assert "Erste Formulierung." not in captured_prompts[0]
    assert "Erste Formulierung." in captured_prompts[1]


# ── Wiederholungs-Vermeidung (_recent_messages/_record_message) ────

def test_record_and_recall_recent_messages(temp_db):
    svc = InsightService(notifications=FakeNotifications())
    assert svc._recent_messages("test_key") == []
    svc._record_message("test_key", "Erste Nachricht.")
    svc._record_message("test_key", "Zweite Nachricht.")
    assert svc._recent_messages("test_key") == ["Erste Nachricht.", "Zweite Nachricht."]


def test_record_message_caps_history(temp_db):
    svc = InsightService(notifications=FakeNotifications())
    for i in range(10):
        svc._record_message("test_key", f"Nachricht {i}", keep=5)
    history = svc._recent_messages("test_key", limit=10)
    assert len(history) == 5
    assert history[-1] == "Nachricht 9"


def test_record_message_ignores_empty():
    svc = InsightService.__new__(InsightService)  # keine DB nötig für diesen Zweig
    # _record_message greift nur bei nicht-leerer message auf die DB zu —
    # ein leerer String darf also ohne temp_db/Connection funktionieren.
    svc._record_message("test_key", "")


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
        "robot_status_enabled": False,
    }})

    class ExplodingPv:
        def get_state(self, sensors):
            raise AssertionError("sollte bei deaktiviertem Insight nicht aufgerufen werden")

    svc = InsightService(pv=ExplodingPv(), notifications=FakeNotifications())
    fired = svc.run_checks()
    assert fired == []


def test_run_checks_creates_notification_for_fired_insight(monkeypatch, temp_db):
    # Nur PV-Überschuss isoliert testen — die anderen beiden Quellen sind
    # seit der Default-Umstellung auf opt-out ebenfalls aktiv und würden
    # sonst echte HA/Wetter-Aufrufe auslösen.
    _enable_insight({"insights": {
        "pv_surplus_enabled": True,
        "fuel_price_enabled": False,
        "weather_tomorrow_enabled": False,
        "robot_status_enabled": False,
    }, "pv": {"enabled": True, "sensors": {}}})
    _fake_llm(monkeypatch, reply="Viel PV-Überschuss gerade.")
    notifications = FakeNotifications()
    svc = InsightService(pv=FakePv(2000), notifications=notifications)
    fired = svc.run_checks()
    assert len(fired) == 1
    assert fired[0]["kind"] == "pv_surplus"
    assert len(notifications.created) == 1
    assert notifications.created[0]["entity_id"] == "pv"


# ── Roboter-Status (Geräte ohne eigene Benachrichtigungsregel) ─────

class FakeRobotService:
    """Konfigurierbarer Ersatz für RobotService — Klassenattribute werden
    pro Test vor dem Monkeypatch gesetzt. `classify` bildet entity_id auf
    "ok"/"warning"/"error" ab; ein fehlender Eintrag simuliert einen nicht
    eindeutig klassifizierten Zustand (z.B. "charging_completed", "drying")
    — die reale RobotService._robot_state_rules()/_normalize_error_state()-
    Kombination wird hier nachgebildet, nicht abgekürzt, damit der Test die
    echte Konservativitäts-Logik in InsightService._robot_severity prüft."""
    robots: list = []
    classify: dict = {}
    translations: dict = {}

    def __init__(self, ha=None):
        pass

    def list_robots_with_config(self, config):
        return type(self).robots

    def _normalize_error_state(self, state):
        return (state or "").strip().lower()

    def _robot_state_rules(self, config, entity_id):
        buckets = {"no_error": set(), "ok": set(), "warn": set(), "critical": set()}
        target = type(self).classify.get(entity_id)
        if target is None:
            return buckets
        robot = next((r for r in type(self).robots if r["entity_id"] == entity_id), None)
        state = self._normalize_error_state(robot["state"]) if robot else ""
        bucket_key = {"ok": "ok", "warning": "warn", "error": "critical"}[target]
        buckets[bucket_key].add(state)
        return buckets

    def _translate_error_state(self, raw_state):
        return type(self).translations.get(raw_state, raw_state)


def _patch_robot_service(monkeypatch, robots, classify, translations=None):
    FakeRobotService.robots = robots
    FakeRobotService.classify = classify
    FakeRobotService.translations = translations or {}
    monkeypatch.setattr("app.services.robot_service.RobotService", FakeRobotService)


def test_robot_status_fires_for_new_warning_uncovered_robot(monkeypatch, temp_db):
    _patch_robot_service(
        monkeypatch,
        robots=[{"entity_id": "vacuum.krumel_knecht", "name": "Krümel Knecht", "state": "error_stuck"}],
        classify={"vacuum.krumel_knecht": "warning"},
        translations={"error_stuck": "Festgefahren"},
    )
    _fake_llm(monkeypatch, reply="Krümel Knecht hat sich mal wieder festgefahren.")
    svc = InsightService(notifications=FakeNotifications())
    result = svc._check_robot_status({})
    assert result == [{
        "entity_id": "vacuum.krumel_knecht",
        "title": "🤖 Krümel Knecht",
        "message": "Krümel Knecht hat sich mal wieder festgefahren.",
    }]


def test_robot_status_skips_entity_with_enabled_rule(monkeypatch, temp_db):
    from app.services.notification_service import NotificationService
    NotificationService().create_rule({
        "label": "Robert", "entity_id": "lawn_mower.robert",
        "condition_type": "changed_to", "condition_value": "trapped", "enabled": True,
    })
    _patch_robot_service(
        monkeypatch,
        robots=[{"entity_id": "lawn_mower.robert", "name": "Robert", "state": "trapped"}],
        classify={"lawn_mower.robert": "error"},
    )
    svc = InsightService(notifications=FakeNotifications())
    result = svc._check_robot_status({})
    assert result == []


def test_robot_status_unclassified_state_does_not_fire(monkeypatch, temp_db):
    """Regression: Live-Check auf erika zeigte, dass saugerspezifische,
    harmlose Zustände wie "charging_completed" oder "drying" in keiner der
    mäher-lastigen Default-Listen stehen und über den alten, generischen
    _severity_for_state()-Fallback fälschlich als "error" durchgerutscht
    wären — das hätte bei jedem Insight-Lauf einen Fehlalarm-Push für
    Carsten/Krümel Knecht ausgelöst. Ein nicht eindeutig klassifizierter
    Zustand darf nie proaktiv gemeldet werden."""
    _patch_robot_service(
        monkeypatch,
        robots=[{"entity_id": "vacuum.carsten_carsten", "name": "Carsten", "state": "charging_completed"}],
        classify={},  # bewusst kein Eintrag -> nicht klassifiziert
    )
    svc = InsightService(notifications=FakeNotifications())
    result = svc._check_robot_status({})
    assert result == []


def test_robot_status_no_refire_on_unchanged_severity(monkeypatch, temp_db):
    _patch_robot_service(
        monkeypatch,
        robots=[{"entity_id": "vacuum.krumel_knecht", "name": "Krümel Knecht", "state": "error_stuck"}],
        classify={"vacuum.krumel_knecht": "warning"},
        translations={"error_stuck": "Festgefahren"},
    )
    _fake_llm(monkeypatch, reply="Krümel Knecht hat sich festgefahren.")
    svc = InsightService(notifications=FakeNotifications())
    first = svc._check_robot_status({})
    assert len(first) == 1
    second = svc._check_robot_status({})
    assert second == []


def test_robot_status_no_fire_on_transition_to_ok_then_fires_on_new_problem(monkeypatch, temp_db):
    _patch_robot_service(
        monkeypatch,
        robots=[{"entity_id": "vacuum.krumel_knecht", "name": "Krümel Knecht", "state": "cleaning"}],
        classify={"vacuum.krumel_knecht": "ok"},
    )
    svc = InsightService(notifications=FakeNotifications())
    baseline = svc._check_robot_status({})
    assert baseline == []  # ok wird nicht gemeldet, nur als Baseline gespeichert

    FakeRobotService.classify = {"vacuum.krumel_knecht": "warning"}
    FakeRobotService.translations = {"cleaning": "Reinigt"}
    _fake_llm(monkeypatch, reply="Krümel Knecht hat jetzt ein Problem.")
    second = svc._check_robot_status({})
    assert len(second) == 1
    assert second[0]["entity_id"] == "vacuum.krumel_knecht"


def test_robot_status_llm_failure_falls_back_to_template(monkeypatch, temp_db):
    _patch_robot_service(
        monkeypatch,
        robots=[{"entity_id": "vacuum.krumel_knecht", "name": "Krümel Knecht", "state": "error_stuck"}],
        classify={"vacuum.krumel_knecht": "error"},
        translations={"error_stuck": "Festgefahren"},
    )

    class FailingRouter:
        def generate(self, payload, timeout_seconds=15):
            raise RuntimeError("kein Netzwerk")
    monkeypatch.setattr("app.brain.llm_client.LLMRouter", FailingRouter)

    svc = InsightService(notifications=FakeNotifications())
    result = svc._check_robot_status({})
    assert result == [{
        "entity_id": "vacuum.krumel_knecht",
        "title": "🤖 Krümel Knecht",
        "message": "Krümel Knecht: Festgefahren.",
    }]


def test_run_checks_creates_notification_for_robot_status(monkeypatch, temp_db):
    _enable_insight({"insights": {
        "robot_status_enabled": True,
        "fuel_price_enabled": False,
        "pv_surplus_enabled": False,
        "weather_tomorrow_enabled": False,
    }})
    _patch_robot_service(
        monkeypatch,
        robots=[{"entity_id": "vacuum.krumel_knecht", "name": "Krümel Knecht", "state": "error_stuck"}],
        classify={"vacuum.krumel_knecht": "warning"},
        translations={"error_stuck": "Festgefahren"},
    )
    _fake_llm(monkeypatch, reply="Krümel Knecht hat sich festgefahren.")
    notifications = FakeNotifications()
    svc = InsightService(notifications=notifications)
    fired = svc.run_checks()
    assert len(fired) == 1
    assert fired[0]["kind"] == "robot_status"
    assert len(notifications.created) == 1
    assert notifications.created[0]["title"] == "🤖 Krümel Knecht"


# ── Fahrzeuge (Ladung fertig / Batterie niedrig) ────────────────────

from app.services.vehicle_service import VehicleService as _RealVehicleService  # noqa: E402


class FakeVehicleService(_RealVehicleService):
    """Erbt von der echten VehicleService, damit die echten
    _is_charging_state/_is_plug_connected_state-Staticmethods verwendet
    werden (kein eigener Nachbau) — nur list_vehicles() wird für Tests
    kontrolliert."""
    data: dict = {"enabled": True, "vehicles": []}

    def __init__(self, ha=None):
        pass

    def list_vehicles(self, config):
        return type(self).data


def _vehicle_entry(battery_pct, charging_state=None, plug_state=None, vehicle_id="veh1", label="Testauto"):
    entry = {
        "id": vehicle_id, "label": label, "ev_profile_enabled": True,
        "battery": {"state": str(battery_pct)},
    }
    if charging_state is not None:
        entry["charging"] = {"state": charging_state}
    if plug_state is not None:
        entry["plug"] = {"state": plug_state}
    return entry


def _patch_vehicle_service(monkeypatch, vehicles, enabled=True):
    FakeVehicleService.data = {"enabled": enabled, "vehicles": vehicles}
    monkeypatch.setattr("app.services.vehicle_service.VehicleService", FakeVehicleService)


_VEHICLE_INSIGHTS_CFG = {"vehicle_battery_low_threshold_pct": 20}


def test_vehicle_charging_finished_fires_on_transition(monkeypatch, temp_db):
    _patch_vehicle_service(monkeypatch, [_vehicle_entry(85, "charging", "connected")])
    svc = InsightService(notifications=FakeNotifications())
    first = svc._check_vehicles({}, _VEHICLE_INSIGHTS_CFG)
    assert first == []  # erster Lauf etabliert nur die Baseline

    _patch_vehicle_service(monkeypatch, [_vehicle_entry(88, "not_charging", "connected")])
    _fake_llm(monkeypatch, reply="Testauto ist voll, kann abgesteckt werden.")
    second = svc._check_vehicles({}, _VEHICLE_INSIGHTS_CFG)
    assert len(second) == 1
    assert second[0]["kind"] == "vehicle_charged"
    assert second[0]["message"] == "Testauto ist voll, kann abgesteckt werden."


def test_vehicle_charging_no_fire_while_continuously_charging(monkeypatch, temp_db):
    _patch_vehicle_service(monkeypatch, [_vehicle_entry(50, "charging", "connected")])
    svc = InsightService(notifications=FakeNotifications())
    svc._check_vehicles({}, _VEHICLE_INSIGHTS_CFG)
    _patch_vehicle_service(monkeypatch, [_vehicle_entry(60, "charging", "connected")])
    second = svc._check_vehicles({}, _VEHICLE_INSIGHTS_CFG)
    assert second == []


def test_vehicle_charging_no_fire_when_unplugged_after_charging(monkeypatch, temp_db):
    """Übergang lädt->lädt nicht mehr OHNE Stecker (weggefahren) ist kein
    "Ladung fertig"-Ereignis."""
    _patch_vehicle_service(monkeypatch, [_vehicle_entry(85, "charging", "connected")])
    svc = InsightService(notifications=FakeNotifications())
    svc._check_vehicles({}, _VEHICLE_INSIGHTS_CFG)
    _patch_vehicle_service(monkeypatch, [_vehicle_entry(84, "not_charging", "disconnected")])
    second = svc._check_vehicles({}, _VEHICLE_INSIGHTS_CFG)
    assert second == []


def test_vehicle_battery_low_fires_when_idle_and_below_threshold(monkeypatch, temp_db):
    _patch_vehicle_service(monkeypatch, [_vehicle_entry(15, "not_charging", "disconnected")])
    _fake_llm(monkeypatch, reply="Testauto hat nur noch 15% Akku.")
    svc = InsightService(notifications=FakeNotifications())
    result = svc._check_vehicles({}, _VEHICLE_INSIGHTS_CFG)
    assert len(result) == 1
    assert result[0]["kind"] == "vehicle_battery_low"
    assert result[0]["message"] == "Testauto hat nur noch 15% Akku."


def test_vehicle_battery_low_no_fire_while_charging(monkeypatch, temp_db):
    _patch_vehicle_service(monkeypatch, [_vehicle_entry(15, "charging", "connected")])
    svc = InsightService(notifications=FakeNotifications())
    result = svc._check_vehicles({}, _VEHICLE_INSIGHTS_CFG)
    assert result == []


def test_vehicle_battery_low_no_refire_while_active(monkeypatch, temp_db):
    _patch_vehicle_service(monkeypatch, [_vehicle_entry(15, "not_charging", "disconnected")])
    _fake_llm(monkeypatch, reply="Niedriger Akku.")
    svc = InsightService(notifications=FakeNotifications())
    first = svc._check_vehicles({}, _VEHICLE_INSIGHTS_CFG)
    assert len(first) == 1
    second = svc._check_vehicles({}, _VEHICLE_INSIGHTS_CFG)
    assert second == []


def test_vehicle_status_skips_non_ev_or_missing_battery(monkeypatch, temp_db):
    entry = {"id": "veh2", "label": "Diesel-Auto", "ev_profile_enabled": False}
    _patch_vehicle_service(monkeypatch, [entry])
    svc = InsightService(notifications=FakeNotifications())
    result = svc._check_vehicles({}, _VEHICLE_INSIGHTS_CFG)
    assert result == []


def test_run_checks_creates_notification_for_vehicle_status(monkeypatch, temp_db):
    _enable_insight({"insights": {
        "vehicle_status_enabled": True,
        "fuel_price_enabled": False,
        "pv_surplus_enabled": False,
        "weather_tomorrow_enabled": False,
        "robot_status_enabled": False,
    }})
    _patch_vehicle_service(monkeypatch, [_vehicle_entry(10, "not_charging", "disconnected")])
    _fake_llm(monkeypatch, reply="Akku niedrig.")
    notifications = FakeNotifications()
    svc = InsightService(notifications=notifications)
    fired = svc.run_checks()
    assert len(fired) == 1
    assert fired[0]["kind"] == "vehicle_battery_low"
    assert notifications.created[0]["title"] == "🔋 Testauto"


# ── Unwetterwarnung ──────────────────────────────────────────────────

class FakeHAState:
    def __init__(self, states):
        self._states = states

    def get_state(self, entity_id):
        return self._states.get(entity_id)


def test_severe_weather_no_entity_configured_returns_none(temp_db):
    svc = InsightService(ha=FakeHAState({}), notifications=FakeNotifications())
    result = svc._check_severe_weather({"severe_weather_entity_id": ""})
    assert result is None


def test_severe_weather_below_threshold_does_not_fire(temp_db):
    states = {"sensor.warn": {"state": "2", "attributes": {"warning_1_headline": "Markante Wetterwarnung"}}}
    svc = InsightService(ha=FakeHAState(states), notifications=FakeNotifications())
    result = svc._check_severe_weather({"severe_weather_entity_id": "sensor.warn"})
    assert result is None


def test_severe_weather_fires_at_level_3(monkeypatch, temp_db):
    states = {"sensor.warn": {"state": "3", "attributes": {
        "warning_1_headline": "Unwetterwarnung vor Sturmböen",
        "warning_1_description": "Schwere Sturmböen bis 100 km/h",
        "region_name": "Melsungen",
    }}}
    _fake_llm(monkeypatch, reply="Achtung, schwere Sturmböen in Melsungen erwartet.")
    svc = InsightService(ha=FakeHAState(states), notifications=FakeNotifications())
    result = svc._check_severe_weather({"severe_weather_entity_id": "sensor.warn"})
    assert result == "Achtung, schwere Sturmböen in Melsungen erwartet."


def test_severe_weather_falls_back_to_attribute_level(monkeypatch, temp_db):
    """Falls der Sensor-Zustand selbst nicht numerisch ist, wird auf das
    warning_1_level-Attribut ausgewichen."""
    states = {"sensor.warn": {"state": "unknown", "attributes": {
        "warning_1_level": "3", "warning_1_headline": "Unwetterwarnung", "region_name": "Melsungen",
    }}}
    _fake_llm(monkeypatch, reply="Warnung Text.")
    svc = InsightService(ha=FakeHAState(states), notifications=FakeNotifications())
    result = svc._check_severe_weather({"severe_weather_entity_id": "sensor.warn"})
    assert result == "Warnung Text."


def test_severe_weather_no_refire_for_same_warning(monkeypatch, temp_db):
    states = {"sensor.warn": {"state": "3", "attributes": {"warning_1_headline": "Unwetterwarnung", "region_name": "Melsungen"}}}
    _fake_llm(monkeypatch, reply="Text.")
    svc = InsightService(ha=FakeHAState(states), notifications=FakeNotifications())
    first = svc._check_severe_weather({"severe_weather_entity_id": "sensor.warn"})
    assert first is not None
    second = svc._check_severe_weather({"severe_weather_entity_id": "sensor.warn"})
    assert second is None


def test_severe_weather_refires_for_new_warning(monkeypatch, temp_db):
    states = {"sensor.warn": {"state": "3", "attributes": {"warning_1_headline": "Unwetterwarnung Sturm", "region_name": "Melsungen"}}}
    ha = FakeHAState(states)
    _fake_llm(monkeypatch, reply="Text 1.")
    svc = InsightService(ha=ha, notifications=FakeNotifications())
    first = svc._check_severe_weather({"severe_weather_entity_id": "sensor.warn"})
    assert first is not None

    ha._states["sensor.warn"] = {"state": "4", "attributes": {"warning_1_headline": "Extreme Unwetterwarnung Tornado", "region_name": "Melsungen"}}
    _fake_llm(monkeypatch, reply="Text 2.")
    second = svc._check_severe_weather({"severe_weather_entity_id": "sensor.warn"})
    assert second is not None
    assert second != first
