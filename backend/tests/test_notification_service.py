from datetime import datetime as _real_datetime

import app.services.notification_service as notification_module
from app.services.integration_config_service import IntegrationConfigService
from app.services.notification_service import NotificationService


class _FixedDateTime(_real_datetime):
    """Ersetzt datetime.now() im notification_service-Modul für die
    Zeitfenster-Tests (gleiches Muster wie in test_insight_service.py)."""
    _fixed = _real_datetime(2024, 1, 1, 10, 0, 0)  # Montag, 10 Uhr

    @classmethod
    def now(cls, tz=None):
        if tz is not None:
            return cls._fixed.replace(tzinfo=tz)
        return cls._fixed


def _set_fixed_now(monkeypatch, year, month, day, hour, minute=0):
    _FixedDateTime._fixed = _real_datetime(year, month, day, hour, minute)
    monkeypatch.setattr(notification_module, "datetime", _FixedDateTime)


def _set_attention_window(**fields):
    defaults = {
        "proactive_enabled": True,
        "proactive_weekday_start": "06:00", "proactive_weekday_end": "22:00",
        "proactive_weekend_start": "08:00", "proactive_weekend_end": "22:00",
    }
    defaults.update(fields)
    IntegrationConfigService().update_config({"attention": defaults})


class FakeHA:
    def __init__(self, state: str):
        self._state = state

    def get_state(self, entity_id):
        return {"state": self._state}


def test_llm_message_falls_back_to_none_on_empty_reply(monkeypatch):
    class FakeRouter:
        def generate(self, payload, timeout_seconds=15):
            return {"reply": "   "}  # leer/nur Leerzeichen

    monkeypatch.setattr("app.brain.llm_client.LLMRouter", FakeRouter)
    result = NotificationService._llm_message("Robert", "changed_to", "trapped", "trapped")
    assert result is None


def test_llm_message_falls_back_to_none_on_exception(monkeypatch):
    class FakeRouter:
        def generate(self, payload, timeout_seconds=15):
            raise RuntimeError("kein Netzwerk")

    monkeypatch.setattr("app.brain.llm_client.LLMRouter", FakeRouter)
    result = NotificationService._llm_message("Robert", "changed_to", "trapped", "trapped")
    assert result is None


def test_llm_message_prompt_uses_translated_state_not_raw_slug(monkeypatch, temp_db):
    """Regression: das LLM hat "outside_wire" fälschlich als "wartet auf sein
    Kabel" gedeutet, weil der rohe HA-Wert unübersetzt in den Prompt kam.
    Der tatsächlich gesendete Prompt muss die deutsche Übersetzung enthalten,
    nicht den rohen Slug."""
    captured_payload = {}

    class FakeRouter:
        def generate(self, payload, timeout_seconds=15):
            captured_payload.update(payload)
            return {"reply": "Robert ist außerhalb der Begrenzung."}

    monkeypatch.setattr("app.brain.llm_client.LLMRouter", FakeRouter)
    NotificationService._llm_message("robert ouside wire", "changed_to", "outside_wire", "outside_wire")
    user_prompt = captured_payload["messages"][1]["content"]
    assert "Außerhalb Begrenzungsdraht" in user_prompt
    assert "outside_wire" not in user_prompt


def test_llm_message_returns_text_on_success(monkeypatch, temp_db):
    class FakeRouter:
        def generate(self, payload, timeout_seconds=15):
            return {"reply": "Robert steckt gerade fest."}

    monkeypatch.setattr("app.brain.llm_client.LLMRouter", FakeRouter)
    result = NotificationService._llm_message("Robert", "changed_to", "trapped", "trapped")
    assert result == "Robert steckt gerade fest."


def test_check_rules_with_use_llm_falls_back_to_auto_message_never_empty(monkeypatch, temp_db):
    """Auch wenn use_llm=1 gesetzt ist und die LLM-Formulierung fehlschlägt,
    darf niemals eine leere Benachrichtigung entstehen."""
    monkeypatch.setattr(NotificationService, "_llm_message", staticmethod(lambda *a, **kw: None))

    svc = NotificationService(ha=FakeHA("trapped"))
    svc.create_rule({
        "label": "Robert", "entity_id": "lawn_mower.robert",
        "condition_type": "changed_to", "condition_value": "trapped",
        "use_llm": True, "enabled": True,
    })
    triggered = svc.check_rules()
    assert len(triggered) == 1
    assert triggered[0]["message"]  # nicht leer
    assert triggered[0]["message"] == "Robert: gewechselt zu Blockiert"  # _auto_message-Fallback, jetzt übersetzt statt Rohwert


def test_create_manual_notification_has_no_rule_id(temp_db):
    svc = NotificationService(ha=FakeHA("idle"))
    notif_id = svc.create_manual_notification("Gleich steht ein Termin an: Zahnarzt um 14:00 Uhr.", entity_id="calendar")
    notifications = svc.list_notifications()
    match = next(n for n in notifications if n["id"] == notif_id)
    assert match["rule_id"] is None
    assert match["entity_id"] == "calendar"
    assert "Zahnarzt" in match["message"]


def test_create_notification_sends_push_with_title(monkeypatch, temp_db):
    calls = []

    def fake_send(title, body, channel="reminders"):
        calls.append({"title": title, "body": body, "channel": channel})
        return 1

    monkeypatch.setattr("app.services.push_service.send_notification", fake_send)

    svc = NotificationService(ha=FakeHA("idle"))
    svc.create_manual_notification("Testnachricht", entity_id="test", title="🔔 Test-Titel")

    assert len(calls) == 1
    assert calls[0]["title"] == "🔔 Test-Titel"
    assert calls[0]["body"] == "Testnachricht"
    assert calls[0]["channel"] == "reminders"


def test_check_rules_uses_rule_label_as_push_title(monkeypatch, temp_db):
    calls = []

    def fake_send(title, body, channel="reminders"):
        calls.append({"title": title, "body": body})
        return 1

    monkeypatch.setattr("app.services.push_service.send_notification", fake_send)

    svc = NotificationService(ha=FakeHA("trapped"))
    svc.create_rule({
        "label": "Robert", "entity_id": "lawn_mower.robert",
        "condition_type": "changed_to", "condition_value": "trapped", "enabled": True,
    })
    svc.check_rules()

    assert len(calls) == 1
    assert calls[0]["title"] == "Robert"


def test_notification_still_created_when_push_raises(monkeypatch, temp_db):
    def failing_send(title, body, channel="reminders"):
        raise RuntimeError("FCM kaputt")

    monkeypatch.setattr("app.services.push_service.send_notification", failing_send)

    svc = NotificationService(ha=FakeHA("idle"))
    notif_id = svc.create_manual_notification("Trotzdem gespeichert", entity_id="test")

    notifications = svc.list_notifications()
    match = next(n for n in notifications if n["id"] == notif_id)
    assert match["message"] == "Trotzdem gespeichert"


def test_entities_with_enabled_rules_excludes_disabled(temp_db):
    svc = NotificationService(ha=FakeHA("idle"))
    svc.create_rule({
        "label": "Robert", "entity_id": "lawn_mower.robert",
        "condition_type": "changed_to", "condition_value": "trapped", "enabled": True,
    })
    svc.create_rule({
        "label": "Alt", "entity_id": "vacuum.old_disabled",
        "condition_type": "changed_to", "condition_value": "error", "enabled": False,
    })
    covered = svc._entities_with_enabled_rules()
    assert covered == {"lawn_mower.robert"}


# ── Wochentag-Zeitfenster für Ansagen ────────────────────────────────

def test_is_within_announce_window_true_during_weekday_hours(monkeypatch, temp_db):
    _set_attention_window()
    _set_fixed_now(monkeypatch, 2024, 1, 1, 10)  # Montag, 10 Uhr
    assert NotificationService._is_within_announce_window() is True


def test_is_within_announce_window_false_at_night_on_weekday(monkeypatch, temp_db):
    _set_attention_window()
    _set_fixed_now(monkeypatch, 2024, 1, 1, 3)  # Montag, 3 Uhr nachts
    assert NotificationService._is_within_announce_window() is False


def test_is_within_announce_window_uses_weekend_fields_on_saturday(monkeypatch, temp_db):
    _set_attention_window()  # Wochentag ab 6, Wochenende ab 8
    _set_fixed_now(monkeypatch, 2024, 1, 6, 7)  # Samstag, 7 Uhr — an einem Wochentag schon offen, am WE noch nicht
    assert NotificationService._is_within_announce_window() is False


def test_is_within_announce_window_false_when_proactive_disabled(monkeypatch, temp_db):
    _set_attention_window(proactive_enabled=False)
    _set_fixed_now(monkeypatch, 2024, 1, 1, 10)
    assert NotificationService._is_within_announce_window() is False


def test_is_within_announce_window_handles_midnight_wraparound(monkeypatch, temp_db):
    _set_attention_window(
        proactive_weekday_start="22:00", proactive_weekday_end="06:00",
        proactive_weekend_start="22:00", proactive_weekend_end="06:00",
    )
    _set_fixed_now(monkeypatch, 2024, 1, 1, 23)  # 23 Uhr — innerhalb des Wrap-Around-Fensters
    assert NotificationService._is_within_announce_window() is True
    _set_fixed_now(monkeypatch, 2024, 1, 1, 12)  # Mittag — außerhalb
    assert NotificationService._is_within_announce_window() is False


def test_create_notification_sets_silent_outside_window(monkeypatch, temp_db):
    _set_attention_window()
    _set_fixed_now(monkeypatch, 2024, 1, 1, 3)  # Montag, 3 Uhr nachts
    svc = NotificationService(ha=FakeHA("idle"))
    notif_id = svc.create_manual_notification("Testnachricht", entity_id="test")
    notifications = svc.list_notifications()
    match = next(n for n in notifications if n["id"] == notif_id)
    assert match["silent"] == 1


def test_create_notification_not_silent_inside_window(monkeypatch, temp_db):
    _set_attention_window()
    _set_fixed_now(monkeypatch, 2024, 1, 1, 10)  # Montag, 10 Uhr
    svc = NotificationService(ha=FakeHA("idle"))
    notif_id = svc.create_manual_notification("Testnachricht", entity_id="test")
    notifications = svc.list_notifications()
    match = next(n for n in notifications if n["id"] == notif_id)
    assert match["silent"] == 0


def test_check_rules_notification_also_respects_window(monkeypatch, temp_db):
    """Termin-Erinnerung, Regeln und Insights laufen alle über denselben
    _create_notification-Kern — hier stellvertretend für Regeln geprüft."""
    _set_attention_window()
    _set_fixed_now(monkeypatch, 2024, 1, 1, 3)  # Montag, 3 Uhr nachts
    svc = NotificationService(ha=FakeHA("trapped"))
    svc.create_rule({
        "label": "Robert", "entity_id": "lawn_mower.robert",
        "condition_type": "changed_to", "condition_value": "trapped", "enabled": True,
    })
    svc.check_rules()
    notifications = svc.list_notifications()
    assert notifications[0]["silent"] == 1
