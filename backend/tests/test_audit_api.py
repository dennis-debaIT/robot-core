import importlib

from fastapi.testclient import TestClient


def test_audit_log_tracks_critical_actions(temp_db):
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        device_patch = client.patch(
            "/device",
            json={
                "device_name": "Erika Küche",
                "site_label": "Haushalt Test",
                "device_state": "network_setup",
                "network_connected": True,
                "server_connected": False,
                "update_status": "available",
            },
        )
        assert device_patch.status_code == 200

        config_patch = client.patch(
            "/config",
            json={"quiet_minutes": 7, "llm_timeout_seconds": 22},
        )
        assert config_patch.status_code == 200

        personality_patch = client.patch(
            "/personality",
            json={"humor": 0.75},
        )
        assert personality_patch.status_code == 200

        audit = client.get("/audit?limit=10")
        assert audit.status_code == 200
        items = audit.json()["items"]
        actions = [item["action"] for item in items]
        assert "device.updated" in actions
        assert "config.updated" in actions
        assert "personality.updated" in actions


def test_audit_log_tracks_person_delete(temp_db):
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        chat = client.post(
            "/chat",
            json={"message": "Ich heiße Dennis. Ich mag Kaffee.", "person_name": "Dennis"},
        )
        assert chat.status_code == 200

        for item in chat.json()["proposed_memories"]:
            approved = client.post(f"/memory/approve/{item['id']}")
            assert approved.status_code == 200

        profiles = client.get("/profiles")
        person_id = profiles.json()["items"][0]["id"]
        deleted = client.delete(f"/profiles/{person_id}")
        assert deleted.status_code == 200

        audit = client.get("/audit?limit=20")
        assert audit.status_code == 200
        items = audit.json()["items"]
        person_delete = next(item for item in items if item["action"] == "person.deleted")
        assert person_delete["target_type"] == "person"
        assert person_delete["details"]["person_name"] == "Dennis"
