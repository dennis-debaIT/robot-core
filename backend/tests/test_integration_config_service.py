from app.database.db import get_connection, write_state
from app.services.integration_config_service import IntegrationConfigService


def test_migrates_old_proactive_window_to_weekday_weekend_fields(temp_db):
    """Regression: das alte, einheitliche Zeitfenster (proactive_start/_end)
    wurde durch getrennte Wochentag-/Wochenend-Felder ersetzt — bestehende
    Nutzer-Anpassungen dürfen dabei nicht verloren gehen."""
    svc = IntegrationConfigService()
    with get_connection() as conn:
        write_state(conn, svc.state_key, {"attention": {"proactive_start": "07:30", "proactive_end": "21:00"}})

    config = svc.get_config()
    attention = config["attention"]
    assert attention["proactive_weekday_start"] == "07:30"
    assert attention["proactive_weekend_start"] == "07:30"
    assert attention["proactive_weekday_end"] == "21:00"
    assert attention["proactive_weekend_end"] == "21:00"
    assert "proactive_start" not in attention
    assert "proactive_end" not in attention


def test_new_installs_get_weekday_weekend_defaults(temp_db):
    config = IntegrationConfigService().get_config()
    attention = config["attention"]
    assert attention["proactive_weekday_start"] == "06:00"
    assert attention["proactive_weekday_end"] == "22:00"
    assert attention["proactive_weekend_start"] == "08:00"
    assert attention["proactive_weekend_end"] == "22:00"


def test_migration_does_not_override_already_migrated_values(temp_db):
    """Ein zweiter get_config()-Aufruf (oder ein Update mit bereits
    migrierten Feldern) darf vom Nutzer gesetzte Wochentag-Werte nicht
    wieder durch die alten Werte überschreiben."""
    svc = IntegrationConfigService()
    with get_connection() as conn:
        write_state(conn, svc.state_key, {
            "attention": {
                "proactive_start": "07:30", "proactive_end": "21:00",
                "proactive_weekday_start": "05:00",
            },
        })

    config = svc.get_config()
    assert config["attention"]["proactive_weekday_start"] == "05:00"
