import importlib

from fastapi.testclient import TestClient


def test_profile_preferences_endpoint_updates_person_specific_response_settings(temp_db):
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
        assert proposed.status_code == 200
        memory_id = proposed.json()["memory"]["id"]
        approved = client.post(f"/memory/approve/{memory_id}")
        assert approved.status_code == 200

        profiles = client.get("/profiles")
        assert profiles.status_code == 200
        person = next(item for item in profiles.json()["items"] if item["name"] == "Dennis")

        patched = client.patch(
            f"/profiles/{person['id']}/preferences",
            json={
                "response_humor_preference": "higher",
                "response_style_preference": "locker",
                "response_length_preference": "short",
            },
        )
        assert patched.status_code == 200
        data = patched.json()
        assert data["preferences"]["response_humor_preference"] == "higher"
        assert data["preferences"]["response_style_preference"] == "locker"
        assert data["preferences"]["response_length_preference"] == "short"


def test_chat_preview_personalizes_prompt_for_specific_person_preferences(temp_db):
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
        assert proposed.status_code == 200
        approved = client.post(f"/memory/approve/{proposed.json()['memory']['id']}")
        assert approved.status_code == 200

        profiles = client.get("/profiles")
        person = next(item for item in profiles.json()["items"] if item["name"] == "Dennis")
        patched = client.patch(
            f"/profiles/{person['id']}/preferences",
            json={
                "response_humor_preference": "higher",
                "response_style_preference": "sachlich",
            },
        )
        assert patched.status_code == 200

        preview = client.post(
            "/chat/preview",
            json={"message": "Hallo", "person_name": "Dennis"},
        )
        assert preview.status_code == 200
        data = preview.json()
        assert data["response_style"] == "sachlich, klar und präzise"
        assert data["personality"]["humor"] > 0.65
        assert "sachlichen, nüchternen Ton" in " ".join(data["context"]["person_preference_lines"])
