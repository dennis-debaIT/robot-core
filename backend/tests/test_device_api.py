import importlib

from fastapi.testclient import TestClient


def test_device_defaults_and_patch(temp_db):
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        initial = client.get("/device")
        assert initial.status_code == 200
        payload = initial.json()
        assert payload["device_name"] == "Erika"
        assert payload["effective_state"] == "factory"
        assert payload["next_step"] == "Gerätename, Standort und Netzwerk hinterlegen."

        patched = client.patch(
            "/device",
            json={
                "device_name": "Erika Wohnzimmer",
                "site_label": "Haushalt Meier",
                "device_state": "ready",
                "network_connected": True,
                "server_connected": True,
                "local_ip": "192.168.1.55",
                "update_status": "idle",
            },
        )
        assert patched.status_code == 200
        data = patched.json()
        assert data["device_name"] == "Erika Wohnzimmer"
        assert data["site_label"] == "Haushalt Meier"
        assert data["effective_state"] == "ready"
        assert data["checklist"][-1]["done"] is True


def test_device_invalid_state_returns_400(temp_db):
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        response = client.patch("/device", json={"device_state": "space_mode"})
        assert response.status_code == 400
        assert response.json()["detail"] == "invalid_device_state"
