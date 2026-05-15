import importlib

from fastapi.testclient import TestClient


def test_config_patch_updates_effective_runtime_values(temp_db):
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        response = client.get("/config")
        assert response.status_code == 200
        data = response.json()
        assert data["effective"]["quiet_minutes"] == 5

        patch = client.patch(
            "/config",
            json={
                "quiet_minutes": 2,
                "response_style": "kurz und direkt",
                "llm_timeout_seconds": 9,
                "llm_max_tokens": 480,
                "llm_history_turns": 4,
                "topic_interest_threshold": 4,
                "topic_interest_window_days": 21,
            },
        )
        assert patch.status_code == 200
        patched = patch.json()
        assert patched["effective"]["quiet_minutes"] == 2
        assert patched["effective"]["response_style"] == "kurz und direkt"
        assert patched["effective"]["llm_max_tokens"] == 480
        assert patched["effective"]["llm_history_turns"] == 4
        assert patched["effective"]["topic_interest_threshold"] == 4
        assert patched["effective"]["topic_interest_window_days"] == 21

        status = client.get("/status")
        assert status.status_code == 200
        payload = status.json()
        assert payload["config"]["quiet_minutes"] == 2
        assert payload["config"]["response_style"] == "kurz und direkt"
        assert payload["config"]["llm_max_tokens"] == 480
        assert payload["config"]["topic_interest_threshold"] == 4
