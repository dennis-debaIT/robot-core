import importlib

from fastapi.testclient import TestClient


def test_global_persona_reset_restores_defaults(temp_db):
    import app.database.db as db_module
    import app.main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    with TestClient(main_module.app) as client:
        patched = client.patch("/personality", json={"humor": 0.1, "friendliness": 0.2})
        assert patched.status_code == 200

        reset = client.post("/personality/reset")
        assert reset.status_code == 200
        data = reset.json()
        assert data["personality"]["humor"] == 0.65
        assert data["personality"]["friendliness"] == 0.9
        assert data["global_relationship_state"]["warmth"] == 0.0
        assert data["global_relationship_state"]["tension"] == 0.0


def test_person_persona_reset_clears_preferences_and_relationship_state(temp_db):
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
        client.patch(
            f"/profiles/{person['id']}/preferences",
            json={"response_style_preference": "sachlich"},
        )

        reset = client.post(f"/profiles/{person['id']}/persona/reset")
        assert reset.status_code == 200
        data = reset.json()
        assert data["preferences"] == {}
        assert data["relationship_state"]["tension"] == 0.0
        assert data["relationship_state"]["warmth"] == 0.0
        assert data["relationship_state"]["interaction_count"] == 0
