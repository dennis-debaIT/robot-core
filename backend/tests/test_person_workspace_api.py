import importlib

from fastapi.testclient import TestClient


def test_profile_workspace_returns_person_state_memories_and_conversation(temp_db):
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        proposed = client.post(
            "/memory/propose",
            json={
                "content": "Der Nutzer heißt Dennis.",
                "category": "person_profile",
                "subject": "Dennis",
                "source": "test",
            },
        )
        memory_id = proposed.json()["memory"]["id"]
        client.post(f"/memory/approve/{memory_id}")
        client.post("/chat", json={"message": "Du nervst heute echt.", "person_name": "Dennis"})

        profiles = client.get("/profiles")
        person = next(item for item in profiles.json()["items"] if item["name"] == "Dennis")

        workspace = client.get(f"/profiles/{person['id']}/workspace")
        assert workspace.status_code == 200
        data = workspace.json()
        assert data["person"]["name"] == "Dennis"
        assert "relationship_state" in data
        assert "memories" in data
        assert "conversation" in data
        assert data["relationship_state"]["interaction_count"] >= 1


def test_memory_endpoint_can_filter_by_subject(temp_db):
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        client.post(
            "/memory/propose",
            json={"content": "Der Nutzer heißt Dennis.", "category": "person_profile", "subject": "Dennis", "source": "test"},
        )
        client.post(
            "/memory/propose",
            json={"content": "Christin mag Kaffee.", "category": "general", "subject": "Christin", "source": "test"},
        )

        dennis = client.get("/memory?subject=Dennis")
        assert dennis.status_code == 200
        items = dennis.json()["items"]
        assert items
        assert all(item["subject"] == "Dennis" for item in items)
